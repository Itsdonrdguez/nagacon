from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.organization import Organization
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead
from app.models.workspace import WorkspaceArtifact
from app.repositories.company import CompanyRepository
from app.services.app_settings_service import get_setting, upsert_setting
from app.services.company_profile_ingest import company_profile_due_for_auto_ingest, run_company_profile_ingest
from app.services.master_catalog_export import write_master_catalog_export
from app.services.search_jobs import start_search_job
from app.services.work_queue import queue_daily_work, workspace_intake_backpressure_snapshot
from app.services.org_service import ensure_default_organization
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle


def _closed_workspace_prep_enabled() -> bool:
    return bool(getattr(settings, "AUTO_CLOSED_WORKSPACE_PREP_ENABLED", True))


def _auto_workspace_prep_enabled(*, db=None, organization_id: int | None = None) -> bool:
    if db is not None:
        configured = get_setting(db, "auto_workspace_prep_enabled", default=None, organization_id=organization_id)
        if configured is not None:
            return str(configured).strip().lower() in {"1", "true", "yes", "on"}
    return bool(getattr(settings, "AUTO_WORKSPACE_PREP_ENABLED", True))


def _auto_workspace_prep_limit() -> int:
    try:
        return max(0, int(getattr(settings, "AUTO_WORKSPACE_PREP_LIMIT", 0) or 0))
    except Exception:
        return 0


def _auto_workspace_prep_cooldown() -> timedelta:
    hours = max(1, int(getattr(settings, "AUTO_WORKSPACE_PREP_COOLDOWN_HOURS", 24) or 24))
    return timedelta(hours=hours)


def _daily_work_enabled() -> bool:
    return bool(getattr(settings, "DAILY_WORK_ENABLED", True))


def _daily_work_limit() -> int:
    return max(1, int(getattr(settings, "DAILY_WORK_LIMIT", 200) or 200))


def _daily_work_run_hour_local() -> int:
    try:
        return min(23, max(0, int(getattr(settings, "DAILY_WORK_RUN_HOUR_LOCAL", 6) or 6)))
    except Exception:
        return 6


def _daily_work_timezone() -> ZoneInfo:
    raw = str(getattr(settings, "DAILY_WORK_TIMEZONE", "America/New_York") or "America/New_York").strip()
    try:
        return ZoneInfo(raw)
    except Exception:
        return ZoneInfo("UTC")


def _daily_work_now() -> datetime:
    return datetime.now(_daily_work_timezone())


def _list_organization_ids(db) -> list[int | None]:
    try:
        ids = [int(row[0]) for row in db.query(Organization.id).order_by(Organization.id.asc()).all() if row and row[0] is not None]
        if ids:
            return ids
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
    org = ensure_default_organization(db)
    return [getattr(org, "id", None)]


def _daily_setting_key(name: str) -> str:
    return f"daily_work_{name}"


def _daily_work_already_completed_today(db, organization_id: int | None, *, current_date: str) -> bool:
    return (get_setting(db, _daily_setting_key("last_run_date"), default="", organization_id=organization_id) or "") == current_date


def _mark_daily_work_attempt(
    db,
    organization_id: int | None,
    *,
    attempted_at: str,
    status: str,
    reason: str = "",
    batch_job_id: str | None = None,
    run_date: str | None = None,
) -> None:
    upsert_setting(db, _daily_setting_key("last_attempted_at"), attempted_at, organization_id=organization_id)
    upsert_setting(db, _daily_setting_key("last_status"), status, organization_id=organization_id)
    upsert_setting(db, _daily_setting_key("last_reason"), reason, organization_id=organization_id)
    if batch_job_id is not None:
        upsert_setting(db, _daily_setting_key("last_batch_job_id"), str(batch_job_id), organization_id=organization_id)
    if run_date:
        upsert_setting(db, _daily_setting_key("last_run_date"), run_date, organization_id=organization_id)
        upsert_setting(db, _daily_setting_key("last_run_at"), attempted_at, organization_id=organization_id)


def run_daily_work_if_due(db) -> dict[str, int]:
    if not _daily_work_enabled():
        return {"scanned_orgs": 0, "ran": 0, "completed": 0, "deferred_backpressure": 0, "skipped_already_run": 0, "skipped_before_hour": 0}

    now = _daily_work_now()
    if now.hour < _daily_work_run_hour_local():
        return {"scanned_orgs": 0, "ran": 0, "completed": 0, "deferred_backpressure": 0, "skipped_already_run": 0, "skipped_before_hour": 1}

    current_date = now.date().isoformat()
    attempted_at = now.isoformat()
    org_ids = _list_organization_ids(db)
    summary = {
        "scanned_orgs": len(org_ids),
        "ran": 0,
        "completed": 0,
        "deferred_backpressure": 0,
        "skipped_already_run": 0,
        "skipped_before_hour": 0,
    }

    for organization_id in org_ids:
        if _daily_work_already_completed_today(db, organization_id, current_date=current_date):
            summary["skipped_already_run"] += 1
            continue
        try:
            result = queue_daily_work(db, organization_id=organization_id, user_id=None, limit=_daily_work_limit())
            summary["ran"] += 1
            skipped_backpressure = int(result.get("skipped_backpressure_count") or 0)
            batch_job_id = result.get("batch_job_id")
            if skipped_backpressure > 0:
                summary["deferred_backpressure"] += 1
                _mark_daily_work_attempt(
                    db,
                    organization_id,
                    attempted_at=attempted_at,
                    status="deferred_backpressure",
                    reason="daily_queue_backpressure",
                    batch_job_id=str(batch_job_id) if batch_job_id is not None else None,
                )
                continue
            summary["completed"] += 1
            _mark_daily_work_attempt(
                db,
                organization_id,
                attempted_at=attempted_at,
                status="completed",
                reason="",
                batch_job_id=str(batch_job_id) if batch_job_id is not None else None,
                run_date=current_date,
            )
        except Exception as exc:
            if hasattr(db, "rollback"):
                db.rollback()
            _mark_daily_work_attempt(
                db,
                organization_id,
                attempted_at=attempted_at,
                status="failed",
                reason=f"{exc.__class__.__name__}: {exc}",
            )
    return summary


def _closed_workspace_prep_limit() -> int:
    try:
        return max(0, int(getattr(settings, "AUTO_CLOSED_WORKSPACE_PREP_LIMIT", 0) or 0))
    except Exception:
        return 0


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


def _workspace_prep_candidates(db, *, now: datetime, organization_id: int | None = None) -> list[Opportunity]:
    query = db.query(Opportunity)
    if organization_id is not None:
        query = query.filter(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            )
        )
    opportunities = (
        query
        .order_by(Opportunity.due_at.asc().nullslast(), Opportunity.id.desc())
        .limit(1000)
        .all()
    )
    candidates: list[Opportunity] = []
    for opp in opportunities:
        if derive_opportunity_lifecycle(getattr(opp, "due_at", None), now=now) == "ARCHIVED":
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


def _needs_workspace_prep(
    opp: Opportunity,
    *,
    document_counts: dict[int, int],
    submission_package_counts: dict[int, int],
    lead_counts: dict[int, int],
    nsn_artifact_counts: dict[int, int],
    part_finder_counts: dict[int, int],
    checklist_counts: dict[int, int],
) -> bool:
    source = str(getattr(opp, "source", "") or "").upper()
    parsed_json = getattr(opp, "parsed_json", None) if isinstance(getattr(opp, "parsed_json", None), dict) else {}
    has_nsn = bool("".join(ch for ch in str((parsed_json.get("nsn") or "")) if ch.isdigit()))
    if document_counts.get(opp.id, 0) == 0:
        return True
    if submission_package_counts.get(opp.id, 0) == 0:
        return True
    if lead_counts.get(opp.id, 0) == 0:
        return True
    if has_nsn and nsn_artifact_counts.get(opp.id, 0) == 0:
        return True
    if has_nsn and part_finder_counts.get(opp.id, 0) == 0:
        return True
    if source == "SAM" and checklist_counts.get(opp.id, 0) == 0:
        return True
    return False


def _existing_workspace_intake_jobs(db, opp_ids: list[int], *, now: datetime) -> set[int]:
    if not opp_ids:
        return set()
    cooldown_cutoff = now - max(_closed_workspace_prep_cooldown(), _auto_workspace_prep_cooldown())
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


def _mark_workspace_prep_attempt(
    db,
    organization_id: int | None,
    *,
    attempted_at: str,
    status: str,
    reason: str = "",
    queued_count: int = 0,
    candidate_count: int = 0,
) -> None:
    upsert_setting(db, "auto_workspace_prep_last_attempted_at", attempted_at, organization_id=organization_id)
    upsert_setting(db, "auto_workspace_prep_last_status", status, organization_id=organization_id)
    upsert_setting(db, "auto_workspace_prep_last_reason", reason, organization_id=organization_id)
    upsert_setting(db, "auto_workspace_prep_last_queued_count", str(int(queued_count or 0)), organization_id=organization_id)
    upsert_setting(db, "auto_workspace_prep_last_candidate_count", str(int(candidate_count or 0)), organization_id=organization_id)
    if status == "completed":
        upsert_setting(db, "auto_workspace_prep_last_completed_at", attempted_at, organization_id=organization_id)


def queue_workspace_prep_for_opportunities(
    db,
    *,
    organization_id: int | None = None,
    manual: bool = False,
) -> dict[str, int | str]:
    if not _auto_workspace_prep_enabled(db=db, organization_id=organization_id):
        return {
            "queued": 0,
            "candidates": 0,
            "skipped_existing": 0,
            "skipped_backpressure": 0,
            "status": "disabled",
        }

    now = datetime.utcnow()
    attempted_at = datetime.now(timezone.utc).isoformat()
    candidates = _workspace_prep_candidates(db, now=now, organization_id=organization_id)
    opp_ids = [opp.id for opp in candidates]
    document_counts = _count_by_opportunity(db, OpportunityFile, opp_ids)
    lead_counts = _count_by_opportunity(db, VendorLead, opp_ids)
    submission_package_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="SUBMISSION_PACKAGE")
    nsn_artifact_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="NSN_INTELLIGENCE")
    part_finder_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="PART_FINDER")
    checklist_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="CHECKLIST")
    existing_jobs = _existing_workspace_intake_jobs(db, opp_ids, now=now)
    backpressure = workspace_intake_backpressure_snapshot(db, organization_id)
    queue_budget = max(0, len(candidates))
    auto_limit = _auto_workspace_prep_limit()
    available_slots = backpressure.get("available_slots")
    automation_batch_limit = backpressure.get("automation_batch_limit")
    if auto_limit > 0:
        queue_budget = min(queue_budget, auto_limit)
    if isinstance(available_slots, int) and available_slots > 0:
        queue_budget = min(queue_budget, available_slots)
    if isinstance(automation_batch_limit, int) and automation_batch_limit > 0:
        queue_budget = min(queue_budget, automation_batch_limit)

    queued = 0
    skipped_existing = 0
    skipped_backpressure = 0
    eligible_candidates = 0
    for opp in candidates:
        if not _needs_workspace_prep(
            opp,
            document_counts=document_counts,
            submission_package_counts=submission_package_counts,
            lead_counts=lead_counts,
            nsn_artifact_counts=nsn_artifact_counts,
            part_finder_counts=part_finder_counts,
            checklist_counts=checklist_counts,
        ):
            continue
        eligible_candidates += 1
        if opp.id in existing_jobs:
            skipped_existing += 1
            continue
        if queued >= queue_budget:
            skipped_backpressure += 1
            continue
        start_search_job(
            "workspace_intake",
            {
                "opportunity_id": opp.id,
                "organization_id": getattr(opp, "organization_id", None) or organization_id,
                "download_documents": True,
                "run_usaspending": True,
                "user_id": None,
                "queued_by": "manual_workspace_prep" if manual else "auto_workspace_prep",
            },
        )
        existing_jobs.add(opp.id)
        queued += 1

    status = "completed"
    reason = ""
    if skipped_backpressure > 0:
        status = "deferred_backpressure"
        reason = "workspace_intake_backpressure"
    elif eligible_candidates == 0:
        status = "nothing_to_queue"
        reason = "all_workspace_prep_requirements_satisfied"

    _mark_workspace_prep_attempt(
        db,
        organization_id,
        attempted_at=attempted_at,
        status=status,
        reason=reason,
        queued_count=queued,
        candidate_count=eligible_candidates,
    )
    return {
        "queued": queued,
        "candidates": eligible_candidates,
        "skipped_existing": skipped_existing,
        "skipped_backpressure": skipped_backpressure,
        "status": status,
    }


def queue_recently_closed_workspace_prep(db) -> dict[str, int]:
    if not _closed_workspace_prep_enabled():
        return {"queued": 0, "candidates": 0, "skipped_existing": 0, "skipped_backpressure": 0}

    now = datetime.utcnow()
    candidates = _recently_closed_candidates(db, now=now)
    opp_ids = [opp.id for opp in candidates]
    document_counts = _count_by_opportunity(db, OpportunityFile, opp_ids)
    lead_counts = _count_by_opportunity(db, VendorLead, opp_ids)
    submission_package_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="SUBMISSION_PACKAGE")
    nsn_artifact_counts = _count_by_opportunity(db, WorkspaceArtifact, opp_ids, artifact_type="NSN_INTELLIGENCE")
    existing_jobs = _existing_workspace_intake_jobs(db, opp_ids, now=now)
    backpressure = workspace_intake_backpressure_snapshot(db, None)
    queue_budget = max(0, len(candidates))
    closed_limit = _closed_workspace_prep_limit()
    available_slots = backpressure.get("available_slots")
    automation_batch_limit = backpressure.get("automation_batch_limit")
    if closed_limit > 0:
        queue_budget = min(queue_budget, closed_limit)
    if isinstance(available_slots, int) and available_slots > 0:
        queue_budget = min(queue_budget, available_slots)
    if isinstance(automation_batch_limit, int) and automation_batch_limit > 0:
        queue_budget = min(queue_budget, automation_batch_limit)

    queued = 0
    skipped_existing = 0
    skipped_backpressure = 0
    for opp in candidates:
        if queued >= queue_budget:
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

    remaining_candidates = max(0, len(candidates) - skipped_existing - queued)
    if queue_budget <= 0:
        skipped_backpressure = remaining_candidates
    elif queued >= queue_budget:
        skipped_backpressure = max(0, remaining_candidates)

    return {
        "queued": queued,
        "candidates": len(candidates),
        "skipped_existing": skipped_existing,
        "skipped_backpressure": skipped_backpressure,
    }


def _auto_ingest_loop(stop_event: threading.Event) -> None:
    poll_seconds = max(60, int(getattr(settings, "AUTO_INGEST_POLL_SECONDS", 900) or 900))
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            profile = CompanyRepository(db).get_first_profile()
            if company_profile_due_for_auto_ingest(profile):
                run_company_profile_ingest(db, profile)
            run_daily_work_if_due(db)
            for organization_id in _list_organization_ids(db):
                queue_workspace_prep_for_opportunities(db, organization_id=organization_id, manual=False)
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
