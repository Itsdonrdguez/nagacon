from __future__ import annotations

import threading
from datetime import datetime, timedelta

from sqlalchemy import func

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead
from app.models.workspace import WorkspaceArtifact
from app.repositories.company import CompanyRepository
from app.services.company_profile_ingest import company_profile_due_for_auto_ingest, run_company_profile_ingest
from app.services.master_catalog_export import write_master_catalog_export
from app.services.search_jobs import start_search_job
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle


def _closed_workspace_prep_enabled() -> bool:
    return bool(getattr(settings, "AUTO_CLOSED_WORKSPACE_PREP_ENABLED", True))


def _closed_workspace_prep_limit() -> int:
    return max(1, int(getattr(settings, "AUTO_CLOSED_WORKSPACE_PREP_LIMIT", 10) or 10))


def _closed_workspace_prep_cooldown() -> timedelta:
    hours = max(1, int(getattr(settings, "AUTO_CLOSED_WORKSPACE_PREP_COOLDOWN_HOURS", 24) or 24))
    return timedelta(hours=hours)


def _recently_closed_candidates(db, *, now: datetime) -> list[Opportunity]:
    opportunities = (
        db.query(Opportunity)
        .filter(Opportunity.due_at.is_not(None))
        .order_by(Opportunity.due_at.desc(), Opportunity.id.desc())
        .limit(500)
        .all()
    )
    candidates: list[Opportunity] = []
    for opp in opportunities:
        if derive_opportunity_lifecycle(getattr(opp, "due_at", None), now=now) != "RECENTLY_CLOSED":
            continue
        candidates.append(opp)
    return candidates


def _count_by_opportunity(db, model, opp_ids: list[int], *, artifact_type: str | None = None) -> dict[int, int]:
    if not opp_ids:
        return {}
    query = db.query(model.opportunity_id, func.count(model.id)).filter(model.opportunity_id.in_(opp_ids))
    if artifact_type and hasattr(model, "artifact_type"):
        query = query.filter(model.artifact_type == artifact_type)
    rows = query.group_by(model.opportunity_id).all()
    return {int(opp_id): int(count) for opp_id, count in rows}


def _needs_closed_workspace_prep(
    opp: Opportunity,
    *,
    document_counts: dict[int, int],
    submission_package_counts: dict[int, int],
    lead_counts: dict[int, int],
    nsn_artifact_counts: dict[int, int],
) -> bool:
    has_nsn = bool("".join(ch for ch in str(((getattr(opp, "parsed_json", None) or {}).get("nsn") or "")) if ch.isdigit()))
    return (
        document_counts.get(opp.id, 0) == 0
        or submission_package_counts.get(opp.id, 0) == 0
        or lead_counts.get(opp.id, 0) == 0
        or (has_nsn and nsn_artifact_counts.get(opp.id, 0) == 0)
    )


def _existing_workspace_intake_jobs(db, opp_ids: list[int], *, now: datetime) -> set[int]:
    if not opp_ids:
        return set()
    cooldown_cutoff = now - _closed_workspace_prep_cooldown()
    rows = (
        db.query(SearchJob)
        .filter(SearchJob.kind == "workspace_intake")
        .filter(
            (SearchJob.status.in_(("queued", "running")))
            | ((SearchJob.status == "success") & (SearchJob.completed_at.is_not(None)) & (SearchJob.completed_at >= cooldown_cutoff))
        )
        .all()
    )
    existing: set[int] = set()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        opp_id = payload.get("opportunity_id") or payload.get("opp_id")
        try:
            opp_id_int = int(opp_id)
        except Exception:
            continue
        if opp_id_int in opp_ids:
            existing.add(opp_id_int)
    return existing


def queue_recently_closed_workspace_prep(db) -> dict[str, int]:
    if not _closed_workspace_prep_enabled():
        return {"queued": 0, "candidates": 0, "skipped_existing": 0}

    now = datetime.utcnow()
    candidates = _recently_closed_candidates(db, now=now)
    opp_ids = [opp.id for opp in candidates]
    document_counts = _count_by_opportunity(db, OpportunityFile, opp_ids)
    lead_counts = _count_by_opportunity(db, VendorLead, opp_ids)
    submission_package_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="SUBMISSION_PACKAGE")
    nsn_artifact_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="NSN_INTELLIGENCE")
    existing_jobs = _existing_workspace_intake_jobs(db, opp_ids, now=now)

    queued = 0
    skipped_existing = 0
    for opp in candidates:
        if queued >= _closed_workspace_prep_limit():
            break
        if not _needs_closed_workspace_prep(
            opp,
            document_counts=document_counts,
            submission_package_counts=submission_package_counts,
            lead_counts=lead_counts,
            nsn_artifact_counts=nsn_artifact_counts,
        ):
            continue
        if opp.id in existing_jobs:
            skipped_existing += 1
            continue
        start_search_job(
            "workspace_intake",
            {
                "opportunity_id": opp.id,
                "organization_id": getattr(opp, "organization_id", None),
                "download_documents": True,
                "run_usaspending": True,
                "user_id": None,
                "queued_by": "auto_closed_workspace_prep",
            },
        )
        existing_jobs.add(opp.id)
        queued += 1

    return {
        "queued": queued,
        "candidates": len(candidates),
        "skipped_existing": skipped_existing,
    }


def _auto_ingest_loop(stop_event: threading.Event) -> None:
    poll_seconds = max(60, int(getattr(settings, "AUTO_INGEST_POLL_SECONDS", 900) or 900))
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            profile = CompanyRepository(db).get_first_profile()
            if company_profile_due_for_auto_ingest(profile):
                run_company_profile_ingest(db, profile)
            queue_recently_closed_workspace_prep(db)
            write_master_catalog_export(db)
        except Exception:
            db.rollback()
        finally:
            db.close()
        stop_event.wait(poll_seconds)


def start_auto_ingest_worker(app) -> None:
    if not bool(getattr(settings, "AUTO_INGEST_ENABLED", True)):
        return
    if str(getattr(settings, "APP_ROLE", "web") or "web").lower() != "web":
        return
    if getattr(app.state, "auto_ingest_thread", None):
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=_auto_ingest_loop, args=(stop_event,), daemon=True, name="nagacon-auto-ingest")
    app.state.auto_ingest_stop_event = stop_event
    app.state.auto_ingest_thread = thread
    thread.start()


def stop_auto_ingest_worker(app) -> None:
    stop_event = getattr(app.state, "auto_ingest_stop_event", None)
    thread = getattr(app.state, "auto_ingest_thread", None)
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    app.state.auto_ingest_thread = None
    app.state.auto_ingest_stop_event = None
