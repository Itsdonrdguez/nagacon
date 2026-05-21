from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentType
from app.models.opportunity import Opportunity
from app.repositories.agents import AgentRunRepository
from app.schemas.agent import AgentRunCreate, AgentRunUpdate
from app.services.pdf_service import download_pdfs_for_opportunity
from app.services.file_retention import (
    mark_opportunity_files_processing_complete,
    prune_closed_opportunity_files_and_storage,
)
from app.services.ingest_enrichment import run_part_finder_enrichment_for_opportunity
from app.services.providers.pdf_cage_extractor import (
    extract_providers_from_opportunity_pdfs,
    seed_vendor_leads_from_providers,
)
from app.services.pricing_intelligence import extract_price_history_for_opportunity
from app.services.intelligence.nsn_intelligence_service import run_nsn_intelligence
from app.services.vendor_service import sync_vendor_leads_from_parsed
from app.services.workspace_service import (
    ensure_parsed,
    generate_checklist,
    generate_quote_email,
    generate_research_brief,
    generate_submission_package,
    generate_vendor_shortlist,
)
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle


def _short_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _rollback_if_active(db: Session) -> None:
    try:
        get_transaction = getattr(db, "get_transaction", None)
        if callable(get_transaction):
            transaction = get_transaction()
            if transaction is None or not getattr(transaction, "is_active", False):
                return
        elif hasattr(db, "in_transaction") and not db.in_transaction():
            return
        db.rollback()
    except Exception:
        pass


def _run_step(db: Session, steps: list[dict[str, Any]], name: str, fn):
    started = datetime.now(timezone.utc).isoformat()
    try:
        output = fn()
        steps.append({"name": name, "status": "success", "started_at": started, "output": output})
        return output
    except Exception as exc:
        _rollback_if_active(db)
        steps.append({"name": name, "status": "failed", "started_at": started, "error": _short_error(exc)})
        return None


def _emit_progress(progress_callback, *, label: str, completed_steps: int, total_steps: int, raw_rows: int | None = None) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(
            {
                "source": "Workspace Intake",
                "label": label,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
                "raw_rows": raw_rows,
            }
        )
    except Exception:
        pass


def _create_pipeline_run(db: Session, opp_id: int) -> tuple[AgentRunRepository | None, int | None]:
    repo = AgentRunRepository(db)
    try:
        run = repo.create(
            AgentRunCreate(
                opportunity_id=opp_id,
                agent_type=AgentType.PROPOSAL,
                input_payload={"pipeline": "opportunity_intake", "opportunity_id": opp_id},
                status="running",
                model_name="deterministic_pipeline",
                started_at=datetime.now(timezone.utc),
            )
        )
        return repo, run.id
    except Exception:
        _rollback_if_active(db)
        return None, None


def _has_part_finder_target(opp: Opportunity, parsed: dict[str, Any] | None = None) -> bool:
    parsed_payload = parsed or {}
    raw_payload = getattr(opp, "raw_payload", None) if isinstance(getattr(opp, "raw_payload", None), dict) else {}
    dibbs_row = raw_payload.get("dibbs_search_row") if isinstance(raw_payload.get("dibbs_search_row"), dict) else {}
    candidates = [
        parsed_payload.get("nsn"),
        parsed_payload.get("compact_nsn"),
        raw_payload.get("nsn"),
        dibbs_row.get("nsn"),
        getattr(opp, "solicitation_number", None),
        getattr(opp, "source_opportunity_id", None),
    ]
    return any(str(candidate or "").strip() for candidate in candidates)


def _finish_pipeline_run(
    db: Session,
    repo: AgentRunRepository | None,
    run_id: int | None,
    *,
    status: str,
    output: dict[str, Any],
    error: str | None = None,
) -> None:
    if not repo or not run_id:
        return
    try:
        repo.update(
            run_id,
            AgentRunUpdate(
                status=status,
                output_payload=output,
                error_message=error,
                completed_at=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _rollback_if_active(db)


def run_opportunity_intake_pipeline(
    db: Session,
    opportunity_id: int,
    *,
    organization_id: int | None = None,
    download_documents: bool = True,
    run_usaspending: bool = True,
    user_id: int | None = None,
    progress_callback=None,
) -> dict[str, Any]:
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if organization_id is not None:
        query = query.filter(Opportunity.organization_id == organization_id)
    opp = query.first()
    if not opp:
        raise ValueError("Opportunity not found")

    repo, run_id = _create_pipeline_run(db, opp.id)
    steps: list[dict[str, Any]] = []
    step_names = []
    if download_documents:
        step_names.append("download_documents")
    step_names.extend(
        [
            "parse_opportunity",
            "generate_part_finder",
            "extract_providers_and_vendor_leads",
            "sync_parsed_vendor_leads",
            "sync_provider_vendor_leads",
            "extract_price_history",
        ]
    )
    if run_usaspending:
        step_names.append("nsn_intelligence")
    step_names.extend(
        [
            "generate_checklist",
            "generate_vendor_shortlist",
            "generate_quote_email",
            "generate_research_brief",
            "generate_submission_package",
        ]
    )
    total_steps = len(step_names)
    completed_steps = 0

    def run_and_progress(name: str, fn):
        nonlocal completed_steps
        _emit_progress(progress_callback, label=name, completed_steps=completed_steps, total_steps=total_steps)
        output = _run_step(db, steps, name, fn)
        completed_steps += 1
        raw_rows = None
        if isinstance(output, dict):
            raw_rows = output.get("created") or output.get("updated") or output.get("parsed_facts") or output.get("seeded_count")
        _emit_progress(progress_callback, label=name, completed_steps=completed_steps, total_steps=total_steps, raw_rows=raw_rows)
        return output

    if download_documents:
        run_and_progress(
            "download_documents",
            lambda: download_pdfs_for_opportunity(db, opp.id, always_snapshot=False, prefer_dibbs_solicitation_detail=True),
        )

    parsed = run_and_progress("parse_opportunity", lambda: ensure_parsed(db, opp)) or {}
    run_and_progress(
        "generate_part_finder",
        lambda: (
            run_part_finder_enrichment_for_opportunity(
                db,
                opp.id,
                organization_id=organization_id,
            )
            if _has_part_finder_target(opp, parsed)
            else {"status": "skipped", "reason": "no_nsn_target"}
        ),
    )

    run_and_progress(
        "extract_providers_and_vendor_leads",
        lambda: extract_providers_from_opportunity_pdfs(
            db,
            opp,
            enrich_with_sam=True,
            organization_id=organization_id,
            user_id=user_id,
        ).model_dump(),
    )

    run_and_progress("sync_parsed_vendor_leads", lambda: sync_vendor_leads_from_parsed(db, opp))
    run_and_progress(
        "sync_provider_vendor_leads",
        lambda: seed_vendor_leads_from_providers(db, opp, parsed=parsed, organization_id=organization_id, user_id=user_id),
    )
    run_and_progress("extract_price_history", lambda: extract_price_history_for_opportunity(db, opp))

    if run_usaspending:
        run_and_progress(
            "nsn_intelligence",
            lambda: run_nsn_intelligence(db, opp, seed_awardees=True, create_summary_artifact=True, user_id=user_id),
        )

    run_and_progress("generate_checklist", lambda: {"artifact_id": generate_checklist(db, opp).id})
    run_and_progress("generate_vendor_shortlist", lambda: {"artifact_id": generate_vendor_shortlist(db, opp).id})
    run_and_progress("generate_quote_email", lambda: {"artifact_id": generate_quote_email(db, opp).id})
    run_and_progress("generate_research_brief", lambda: {"artifact_id": generate_research_brief(db, opp).id})
    run_and_progress("generate_submission_package", lambda: {"artifact_id": generate_submission_package(db, opp).id})

    failed = [step for step in steps if step["status"] == "failed"]
    output = {
        "pipeline": "opportunity_intake",
        "opportunity_id": opp.id,
        "status": "completed_with_errors" if failed else "completed",
        "steps": steps,
        "failed_step_count": len(failed),
    }
    mark_opportunity_files_processing_complete(
        db,
        opp.id,
        completed=not failed,
        source="opportunity_intake_pipeline",
        details={
            "failed_step_count": len(failed),
            "status": output["status"],
        },
    )
    _finish_pipeline_run(
        db,
        repo,
        run_id,
        status="failed" if failed else "success",
        output=output,
        error="; ".join(step["error"] for step in failed[:3]) if failed else None,
    )
    if (
        not failed
        and bool(getattr(settings, "AUTO_CLOSED_WORKSPACE_STORAGE_CLEANUP_ENABLED", True))
        and derive_opportunity_lifecycle(getattr(opp, "due_at", None)) in {"RECENTLY_CLOSED", "ARCHIVED"}
    ):
        output["closed_storage_cleanup"] = prune_closed_opportunity_files_and_storage(
            db,
            opp.id,
            require_closed=True,
            source="closed_workspace_cleanup",
        )
    return output
