from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.pipeline_item import PipelineItem
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact, WorkspaceTask
from app.services.search_jobs import record_search_job, start_search_job
from app.utils.opportunity_lifecycle import is_archived_opportunity


HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
QUEUEABLE_TYPES = {"AWARDEE_ENRICHMENT_READY", "NSN_INTELLIGENCE_REFRESH"}
QUEUEABLE_JOB_KINDS = {"awardee_enrichment", "nsn_build"}
COMPLETED_QUEUE_COOLDOWN_HOURS = 12

MISSION_BUCKET_LABELS = {
    "due_soon": "Due Soon",
    "needs_suppliers": "Needs Suppliers",
    "rfq_not_sent": "RFQ Not Sent",
    "follow_up_due": "Follow-up Due",
    "ready_to_submit": "Ready to Submit",
    "submission_prep": "Submission Prep",
    "closed_intelligence": "Closed Intelligence",
    "failed": "Failed",
    "manual_review": "Manual Review",
}


def _scope_org(query, model, organization_id: int | None):
    if organization_id is None or not hasattr(model, "organization_id"):
        return query
    return query.filter(or_(model.organization_id == organization_id, model.organization_id.is_(None)))


def _days_until(value: datetime | None, now: datetime) -> int | None:
    if not value:
        return None
    return (value.date() - now.date()).days


def _extract_nsn(opp: Opportunity) -> str | None:
    parsed = getattr(opp, "parsed_json", None) or {}
    raw_payload = getattr(opp, "raw_payload", None) or {}
    candidates = [
        parsed.get("nsn"),
        parsed.get("compact_nsn"),
        raw_payload.get("nsn"),
        (raw_payload.get("dibbs_search_row") or {}).get("nsn") if isinstance(raw_payload.get("dibbs_search_row"), dict) else None,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return None


def _opp_payload(opp: Opportunity) -> dict[str, Any]:
    return {
        "id": opp.id,
        "title": getattr(opp, "display_title", None) or opp.title,
        "solicitation_number": opp.solicitation_number,
        "source": opp.source,
        "agency": opp.agency,
        "fsc": getattr(opp, "fsc", None),
        "due_at": opp.due_at.isoformat() if opp.due_at else None,
        "workspace_url": f"/workspace/{opp.id}",
    }


def _item(
    item_type: str,
    priority: str,
    opp: Opportunity,
    title: str,
    subtitle: str,
    action_label: str = "Open Workspace",
    meta: dict[str, Any] | None = None,
    due_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{item_type}:{opp.id}:{(meta or {}).get('quote_id') or (meta or {}).get('key') or 'main'}",
        "type": item_type,
        "priority": priority,
        "title": title,
        "subtitle": subtitle,
        "opportunity": _opp_payload(opp),
        "due_at": due_at.isoformat() if due_at else (opp.due_at.isoformat() if opp.due_at else None),
        "action_label": action_label,
        "action_url": f"/workspace/{opp.id}",
        "meta": meta or {},
    }


def _mission_bucket(item_type: str) -> str:
    normalized = str(item_type or "").upper()
    if normalized in {"RFQ_CLOSING_SOON"}:
        return "due_soon"
    if normalized in {"MISSING_VENDOR_LEADS", "MISSING_PART_FINDER", "NSN_INTELLIGENCE_REFRESH"}:
        return "needs_suppliers"
    if normalized in {"RFQ_NOT_SENT"}:
        return "rfq_not_sent"
    if normalized in {"QUOTE_FOLLOW_UP_DUE", "QUOTE_REQUESTED_NO_RESPONSE"}:
        return "follow_up_due"
    if normalized in {"READY_TO_SUBMIT"}:
        return "ready_to_submit"
    if normalized in {
        "MISSING_SUBMISSION_PACKAGE",
        "SAM_CHECKLIST_MISSING",
        "SAM_COMPLIANCE_MATRIX_MISSING",
        "SAM_CO_EMAIL_MISSING",
        "SAM_TARGET_SUBMIT_DATE_MISSING",
        "SAM_TASKS_NOT_SEEDED",
        "SAM_OPEN_TASKS_MISSING",
        "SAM_SUBMISSION_PACKAGE_MISSING",
        "DIBBS_RFQ_PACKAGE_MISSING",
    }:
        return "submission_prep"
    if normalized in {"AWARDEE_ENRICHMENT_READY"}:
        return "closed_intelligence"
    return "manual_review"


def _display_status(item_type: str, priority: str, *, queue_state: dict[str, Any] | None = None, failed: bool = False) -> str:
    if failed:
        return "FAILED"
    if queue_state:
        status = str(queue_state.get("status") or "").strip().upper()
        if status:
            return status
    normalized = str(item_type or "").upper()
    if normalized in {"SAM_COMPLIANCE_MATRIX_MISSING", "SAM_TARGET_SUBMIT_DATE_MISSING", "SAM_OPEN_TASKS_MISSING"}:
        return "NEEDS REVIEW"
    if normalized in {"RFQ_NOT_SENT", "READY_TO_SUBMIT"}:
        return "OPEN"
    if normalized in {"QUOTE_FOLLOW_UP_DUE"}:
        return "FOLLOW-UP"
    if normalized in {"AWARDEE_ENRICHMENT_READY"}:
        return "CLOSED"
    return "OPEN" if priority in {HIGH, MEDIUM, LOW} else "PENDING"


def _decorate_mission_item(item: dict[str, Any], *, queue_state: dict[str, Any] | None = None, failed: bool = False) -> dict[str, Any]:
    bucket = _mission_bucket(item.get("type"))
    return {
        **item,
        "mission_bucket": bucket,
        "mission_bucket_label": MISSION_BUCKET_LABELS.get(bucket, "Manual Review"),
        "display_status": _display_status(item.get("type"), item.get("priority", ""), queue_state=queue_state, failed=failed),
    }


def _normalize_nsn(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits or None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        return str(value)


def _freeze_signature_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_signature_value(inner)) for key, inner in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze_signature_value(item) for item in value)
    return value


def _opportunity_fingerprint(opp: Opportunity, nsn: str | None = None) -> str:
    payload = {
        "id": opp.id,
        "source": opp.source,
        "solicitation_number": opp.solicitation_number,
        "title": getattr(opp, "display_title", None) or opp.title,
        "agency": opp.agency,
        "due_at": opp.due_at.isoformat() if opp.due_at else None,
        "status": opp.status,
        "fsc": getattr(opp, "fsc", None),
        "set_aside": getattr(opp, "set_aside", None),
        "nsn": nsn or _extract_nsn(opp),
        "parsed_json": getattr(opp, "parsed_json", None) or {},
        "raw_payload": getattr(opp, "raw_payload", None) or {},
    }
    return hashlib.sha1(_stable_json(payload).encode("utf-8")).hexdigest()


def _count_by_opportunity(db: Session, model, organization_id: int | None, artifact_type: str | None = None) -> dict[int, int]:
    query = db.query(model.opportunity_id, func.count(model.id))
    query = _scope_org(query, model, organization_id)
    if artifact_type and hasattr(model, "artifact_type"):
        query = query.filter(model.artifact_type == artifact_type)
    rows = query.group_by(model.opportunity_id).all()
    return {int(opp_id): int(count) for opp_id, count in rows}


def _active_queueable_jobs(
    db: Session,
    organization_id: int | None,
    user_id: int | None = None,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    query = db.query(SearchJob).filter(
        SearchJob.status.in_(("queued", "running")),
        SearchJob.kind.in_(("awardee_enrichment", "nsn_build")),
    )
    query = _scope_org(query, SearchJob, organization_id)
    if user_id is not None:
        query = query.filter(SearchJob.user_id == user_id)
    rows = query.all()
    active: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        active[_job_signature(row.kind, payload)] = {
            "job_id": row.id,
            "kind": row.kind,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "progress": dict(row.progress or {}),
        }
    return active


def _recent_completed_queueable_jobs(
    db: Session,
    organization_id: int | None,
    user_id: int | None = None,
    *,
    now: datetime,
    cooldown_hours: int = COMPLETED_QUEUE_COOLDOWN_HOURS,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    cutoff = now - timedelta(hours=cooldown_hours)
    query = db.query(SearchJob).filter(
        SearchJob.status == "success",
        SearchJob.kind.in_(tuple(QUEUEABLE_JOB_KINDS)),
        SearchJob.completed_at.is_not(None),
        SearchJob.completed_at >= cutoff,
    )
    query = _scope_org(query, SearchJob, organization_id)
    if user_id is not None:
        query = query.filter(SearchJob.user_id == user_id)
    rows = query.order_by(SearchJob.completed_at.desc(), SearchJob.created_at.desc()).all()
    recent: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        signature = _job_signature(row.kind, payload)
        if signature in recent:
            continue
        recent[signature] = {
            "job_id": row.id,
            "kind": row.kind,
            "status": row.status,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "result": row.result if isinstance(row.result, dict) else {},
            "payload": payload,
        }
    return recent


def _recent_failed_queueable_jobs(
    db: Session,
    organization_id: int | None,
    user_id: int | None = None,
    *,
    now: datetime,
    cooldown_hours: int = COMPLETED_QUEUE_COOLDOWN_HOURS,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    cutoff = now - timedelta(hours=cooldown_hours)
    query = db.query(SearchJob).filter(
        SearchJob.status == "failed",
        SearchJob.kind.in_(tuple(QUEUEABLE_JOB_KINDS)),
        SearchJob.completed_at.is_not(None),
        SearchJob.completed_at >= cutoff,
    )
    query = _scope_org(query, SearchJob, organization_id)
    if user_id is not None:
        query = query.filter(SearchJob.user_id == user_id)
    rows = query.order_by(SearchJob.completed_at.desc(), SearchJob.created_at.desc()).all()
    recent: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        signature = _job_signature(row.kind, payload)
        if signature in recent:
            continue
        recent[signature] = {
            "job_id": row.id,
            "kind": row.kind,
            "status": row.status,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "error": row.error,
            "payload": payload,
        }
    return recent


def build_daily_work_queue(
    db: Session,
    organization_id: int | None = None,
    user_id: int | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.utcnow()
    active_queueable_jobs = _active_queueable_jobs(db, organization_id, user_id=user_id)
    recent_completed_jobs = _recent_completed_queueable_jobs(db, organization_id, user_id=user_id, now=current_time)
    recent_failed_jobs = _recent_failed_queueable_jobs(db, organization_id, user_id=user_id, now=current_time)

    opp_query = db.query(Opportunity)
    opp_query = _scope_org(opp_query, Opportunity, organization_id)
    opportunities = (
        opp_query
        .order_by(Opportunity.due_at.asc().nullslast(), Opportunity.id.desc())
        .limit(limit)
        .all()
    )
    opp_by_id = {opp.id: opp for opp in opportunities}
    opp_ids = list(opp_by_id)
    if not opp_ids:
        return {"items": [], "summary": {}, "total": 0, "generated_at": current_time.isoformat()}

    lead_counts = _count_by_opportunity(db, VendorLead, organization_id)
    quote_counts = _count_by_opportunity(db, VendorQuote, organization_id)
    part_finder_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="PART_FINDER")
    submission_package_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="SUBMISSION_PACKAGE")
    nsn_artifact_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="NSN_INTELLIGENCE")
    checklist_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="CHECKLIST")
    co_email_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="CO_EMAIL_DRAFT")
    compliance_matrix_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="COMPLIANCE_MATRIX")
    document_counts = _count_by_opportunity(db, WorkspaceArtifact, organization_id, artifact_type="DOCUMENT_PIPELINE")
    task_counts = _count_by_opportunity(db, WorkspaceTask, organization_id)

    open_task_query = db.query(WorkspaceTask.opportunity_id, func.count(WorkspaceTask.id))
    open_task_query = _scope_org(open_task_query, WorkspaceTask, organization_id)
    open_task_rows = (
        open_task_query
        .filter(WorkspaceTask.status.in_(("OPEN", "IN_PROGRESS")))
        .group_by(WorkspaceTask.opportunity_id)
        .all()
    )
    open_task_counts = {int(opp_id): int(count) for opp_id, count in open_task_rows}

    submissions_query = db.query(BidSubmission).filter(BidSubmission.opportunity_id.in_(opp_ids))
    submissions = {row.opportunity_id: row for row in submissions_query.all()}
    pipeline_query = db.query(PipelineItem).filter(PipelineItem.opportunity_id.in_(opp_ids))
    pipeline_query = _scope_org(pipeline_query, PipelineItem, organization_id)
    pipelines = {row.opportunity_id: row for row in pipeline_query.all()}

    quote_query = db.query(VendorQuote).filter(VendorQuote.opportunity_id.in_(opp_ids))
    quote_query = _scope_org(quote_query, VendorQuote, organization_id)
    quotes = quote_query.all()

    items: list[dict[str, Any]] = []
    in_progress_items: list[dict[str, Any]] = []
    recent_completed_items: list[dict[str, Any]] = []
    recent_failed_items: list[dict[str, Any]] = []

    for quote in quotes:
        opp = opp_by_id.get(quote.opportunity_id)
        if not opp:
            continue
        status = str(quote.status or "").upper()
        if status == "REQUESTED" and quote.next_follow_up_at and quote.next_follow_up_at <= current_time:
            items.append(_item(
                "QUOTE_FOLLOW_UP_DUE",
                HIGH,
                opp,
                f"Follow up with {quote.company_name or quote.cage}",
                f"Quote request is due for follow-up. CAGE {quote.cage}.",
                meta={"quote_id": quote.id, "cage": quote.cage, "company_name": quote.company_name},
                due_at=quote.next_follow_up_at,
            ))
        elif status == "REQUESTED" and not quote.unit_price:
            items.append(_item(
                "QUOTE_REQUESTED_NO_RESPONSE",
                MEDIUM,
                opp,
                f"Awaiting quote from {quote.company_name or quote.cage}",
                "Quote has been requested but no price has been logged yet.",
                meta={"quote_id": quote.id, "cage": quote.cage, "company_name": quote.company_name},
                due_at=quote.next_follow_up_at,
            ))

    for opp in opportunities:
        if is_archived_opportunity(getattr(opp, "due_at", None), now=current_time):
            continue
        days_left = _days_until(opp.due_at, current_time)
        is_open = days_left is None or days_left >= 0
        nsn = _extract_nsn(opp)
        opportunity_quotes = [quote for quote in quotes if quote.opportunity_id == opp.id]
        requested_quotes = [quote for quote in opportunity_quotes if str(getattr(quote, "status", "") or "").strip().upper() == "REQUESTED"]
        received_quotes = [quote for quote in opportunity_quotes if str(getattr(quote, "status", "") or "").strip().upper() == "RECEIVED"]
        not_requested_quotes = [quote for quote in opportunity_quotes if str(getattr(quote, "status", "") or "").strip().upper() in {"NOT_REQUESTED", ""}]
        has_selected_quote = bool(getattr(submissions.get(opp.id), "planned_vendor_quote_id", None)) or bool(
            getattr(submissions.get(opp.id), "planned_vendor_cage", None)
        )
        if days_left is not None and 0 <= days_left <= 7:
            priority = HIGH if days_left <= 2 else MEDIUM
            items.append(_item(
                "RFQ_CLOSING_SOON",
                priority,
                opp,
                f"{opp.solicitation_number} closes soon",
                "Due today." if days_left == 0 else f"Due in {days_left} day{'s' if days_left != 1 else ''}.",
                meta={"days_left": days_left},
                due_at=opp.due_at,
            ))

        if is_open and lead_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "MISSING_VENDOR_LEADS",
                MEDIUM,
                opp,
                "Find vendor leads",
                "No vendor leads are attached to this opportunity yet.",
                action_label="Open Vendor Research",
                meta={
                    "lead_count": 0,
                    "nsn": nsn,
                    "fsc": getattr(opp, "fsc", None),
                    "title": getattr(opp, "display_title", None) or opp.title,
                    "agency": getattr(opp, "agency", None),
                },
            ))

        if is_open and nsn and part_finder_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "MISSING_PART_FINDER",
                MEDIUM,
                opp,
                "Run Part Finder",
                f"NSN {nsn} is available, but no Part Finder result is saved yet.",
                action_label="Open Part Finder",
                meta={"nsn": nsn},
            ))

        if is_open and lead_counts.get(opp.id, 0) > 0 and quote_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "RFQ_NOT_SENT",
                HIGH if days_left is not None and days_left <= 3 else MEDIUM,
                opp,
                f"Send RFQ to {lead_counts.get(opp.id, 0)} supplier{'s' if lead_counts.get(opp.id, 0) != 1 else ''}",
                "Supplier candidates exist, but no RFQ request has been sent yet.",
                action_label="Open RFQ Draft",
                meta={"lead_count": lead_counts.get(opp.id, 0), "nsn": nsn},
                due_at=opp.due_at,
            ))

        if is_open and quote_counts.get(opp.id, 0) > 0 and not requested_quotes and not received_quotes and submission_package_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "MISSING_SUBMISSION_PACKAGE",
                LOW,
                opp,
                "Build submission package",
                "Quote records exist, but no submission package artifact has been saved.",
                meta={"quote_count": quote_counts.get(opp.id, 0)},
            ))

        if is_open and not_requested_quotes:
            items.append(_item(
                "RFQ_NOT_SENT",
                HIGH if days_left is not None and days_left <= 3 else MEDIUM,
                opp,
                f"Send RFQ to {len(not_requested_quotes)} supplier{'s' if len(not_requested_quotes) != 1 else ''}",
                "Quote records exist, but outreach has not been marked sent yet.",
                action_label="Open RFQ Draft",
                meta={
                    "quote_ids": [quote.id for quote in not_requested_quotes],
                    "quote_count": len(not_requested_quotes),
                    "nsn": nsn,
                },
                due_at=opp.due_at,
            ))

        if is_open and (received_quotes or has_selected_quote):
            items.append(_item(
                "READY_TO_SUBMIT",
                HIGH if days_left is not None and days_left <= 3 else MEDIUM,
                opp,
                "Prepare submission package",
                "A quote has been received and the package can move toward submission.",
                action_label="Open Submission Package",
                meta={
                    "received_quote_count": len(received_quotes),
                    "selected_quote": has_selected_quote,
                },
                due_at=opp.due_at,
            ))

        if str(getattr(opp, "source", "") or "").upper() == "SAM" and is_open:
            pipeline = pipelines.get(opp.id)
            if checklist_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "SAM_CHECKLIST_MISSING",
                    HIGH if days_left is not None and days_left <= 7 else MEDIUM,
                    opp,
                    "Start the proposal checklist",
                    "No proposal checklist artifact is saved for this SAM opportunity yet.",
                    action_label="Open Proposal Workspace",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))
            if checklist_counts.get(opp.id, 0) > 0 and compliance_matrix_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "SAM_COMPLIANCE_MATRIX_MISSING",
                    HIGH if days_left is not None and days_left <= 10 else MEDIUM,
                    opp,
                    "Build the compliance matrix",
                    "A proposal checklist exists, but the compliance matrix has not been generated yet.",
                    action_label="Open Proposal Workspace",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))
            if co_email_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "SAM_CO_EMAIL_MISSING",
                    MEDIUM,
                    opp,
                    "Draft contracting officer outreach",
                    "No contracting officer email draft is saved yet for this SAM opportunity.",
                    action_label="Open CO Draft",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))
            if pipeline is None:
                items.append(_item(
                    "SAM_PIPELINE_SETUP",
                    LOW,
                    opp,
                    "Create a proposal workspace record",
                    "No proposal tracking record exists yet for this SAM opportunity.",
                    action_label="Open Workspace",
                    meta={},
                    due_at=opp.due_at,
                ))
            if pipeline is not None and getattr(pipeline, "target_submit_date", None) is None:
                items.append(_item(
                    "SAM_TARGET_SUBMIT_DATE_MISSING",
                    MEDIUM,
                    opp,
                    "Set the target submit date",
                    "Proposal tracking exists, but the target submit date is still blank.",
                    action_label="Open Proposal Workspace",
                    meta={"decision_status": getattr(getattr(pipeline, "decision_status", None), "value", getattr(pipeline, "decision_status", None))},
                    due_at=opp.due_at,
                ))
            if checklist_counts.get(opp.id, 0) > 0 and task_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "SAM_TASKS_NOT_SEEDED",
                    MEDIUM,
                    opp,
                    "Seed proposal tasks",
                    "The proposal checklist exists, but no workspace tasks have been created yet.",
                    action_label="Open Proposal Workspace",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))
            if pipeline is not None and open_task_counts.get(opp.id, 0) == 0 and getattr(getattr(pipeline, "decision_status", None), "value", getattr(pipeline, "decision_status", None)) in {"IN_PROGRESS", "BID"}:
                items.append(_item(
                    "SAM_OPEN_TASKS_MISSING",
                    HIGH if days_left is not None and days_left <= 7 else MEDIUM,
                    opp,
                    "Add active proposal tasks",
                    "This opportunity is in an active proposal stage, but there are no open workspace tasks right now.",
                    action_label="Open Proposal Workspace",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))
            if pipeline is not None and getattr(getattr(pipeline, "decision_status", None), "value", getattr(pipeline, "decision_status", None)) in {"IN_PROGRESS", "BID"} and submission_package_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "SAM_SUBMISSION_PACKAGE_MISSING",
                    HIGH if days_left is not None and days_left <= 5 else MEDIUM,
                    opp,
                    "Build the submission package",
                    "Proposal work is active, but no submission package artifact has been saved yet.",
                    action_label="Open Submission Package",
                    meta={"days_left": days_left},
                    due_at=opp.due_at,
                ))

        if str(getattr(opp, "source", "") or "").upper() == "DIBBS" and is_open:
            if document_counts.get(opp.id, 0) == 0:
                items.append(_item(
                    "DIBBS_RFQ_PACKAGE_MISSING",
                    HIGH if days_left is not None and days_left <= 7 else MEDIUM,
                    opp,
                    "Download the RFQ package",
                    "No RFQ package or document pipeline artifact is saved yet for this DIBBS opportunity.",
                    action_label="Open RFQ Package",
                    meta={"days_left": days_left, "nsn": nsn},
                    due_at=opp.due_at,
                ))

        submission = submissions.get(opp.id)
        if days_left is not None and days_left < 0:
            candidate = _item(
                "AWARDEE_ENRICHMENT_READY",
                LOW,
                opp,
                "Check awardee enrichment",
                "Solicitation is closed. Use it to improve awardee and vendor intelligence.",
                action_label="Open Closed Intelligence",
                meta={
                    "submission_status": getattr(submission, "status", None),
                    "days_since_close": abs(days_left),
                    "opportunity_fingerprint": _opportunity_fingerprint(opp, nsn),
                },
            )
            spec = _queue_job_spec(candidate, organization_id)
            signature = _job_signature(spec["kind"], spec["payload"]) if spec else None
            if signature and signature in active_queueable_jobs:
                in_progress_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": active_queueable_jobs[signature],
                        },
                        queue_state=active_queueable_jobs[signature],
                    )
                )
            elif (
                signature
                and signature in recent_completed_jobs
                and recent_completed_jobs[signature].get("payload", {}).get("opportunity_fingerprint") == candidate.get("meta", {}).get("opportunity_fingerprint")
            ):
                recent_completed_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": recent_completed_jobs[signature],
                        },
                        queue_state=recent_completed_jobs[signature],
                    )
                )
            elif (
                signature
                and signature in recent_failed_jobs
                and recent_failed_jobs[signature].get("payload", {}).get("opportunity_fingerprint") == candidate.get("meta", {}).get("opportunity_fingerprint")
            ):
                recent_failed_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": recent_failed_jobs[signature],
                        },
                        queue_state=recent_failed_jobs[signature],
                        failed=True,
                    )
                )
            else:
                items.append(candidate)

        if nsn and nsn_artifact_counts.get(opp.id, 0) == 0:
            candidate = _item(
                "NSN_INTELLIGENCE_REFRESH",
                LOW,
                opp,
                "Refresh NSN intelligence",
                f"NSN {nsn} has no saved intelligence artifact yet.",
                action_label="Open NSN Intelligence",
                meta={"nsn": nsn, "opportunity_fingerprint": _opportunity_fingerprint(opp, nsn)},
            )
            spec = _queue_job_spec(candidate, organization_id)
            signature = _job_signature(spec["kind"], spec["payload"]) if spec else None
            if signature and signature in active_queueable_jobs:
                in_progress_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": active_queueable_jobs[signature],
                        },
                        queue_state=active_queueable_jobs[signature],
                    )
                )
            elif (
                signature
                and signature in recent_completed_jobs
                and recent_completed_jobs[signature].get("payload", {}).get("opportunity_fingerprint") == candidate.get("meta", {}).get("opportunity_fingerprint")
            ):
                recent_completed_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": recent_completed_jobs[signature],
                        },
                        queue_state=recent_completed_jobs[signature],
                    )
                )
            elif (
                signature
                and signature in recent_failed_jobs
                and recent_failed_jobs[signature].get("payload", {}).get("opportunity_fingerprint") == candidate.get("meta", {}).get("opportunity_fingerprint")
            ):
                recent_failed_items.append(
                    _decorate_mission_item(
                        {
                            **candidate,
                            "queue_state": recent_failed_jobs[signature],
                        },
                        queue_state=recent_failed_jobs[signature],
                        failed=True,
                    )
                )
            else:
                items.append(candidate)

    priority_order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    items = [_decorate_mission_item(item) for item in items]
    items.sort(key=lambda item: (priority_order.get(item["priority"], 9), item.get("due_at") or "9999", item["type"]))
    in_progress_items.sort(key=lambda item: (item.get("queue_state", {}).get("status") != "running", item["type"], item["title"]))
    recent_completed_items.sort(key=lambda item: (item.get("queue_state", {}).get("completed_at") or "", item["type"], item["title"]), reverse=True)
    recent_failed_items.sort(key=lambda item: (item.get("queue_state", {}).get("completed_at") or "", item["type"], item["title"]), reverse=True)
    summary: dict[str, int] = {}
    for item in items:
        summary[item["type"]] = summary.get(item["type"], 0) + 1
        summary[item["priority"]] = summary.get(item["priority"], 0) + 1
        bucket = item.get("mission_bucket")
        if bucket:
            summary[bucket] = summary.get(bucket, 0) + 1
    in_progress_summary: dict[str, int] = {}
    for item in in_progress_items:
        in_progress_summary[item["type"]] = in_progress_summary.get(item["type"], 0) + 1
        bucket = item.get("mission_bucket")
        if bucket:
            in_progress_summary[bucket] = in_progress_summary.get(bucket, 0) + 1
        queue_status = str((item.get("queue_state") or {}).get("status") or "").upper()
        if queue_status:
            in_progress_summary[queue_status] = in_progress_summary.get(queue_status, 0) + 1
    recent_completed_summary: dict[str, int] = {}
    for item in recent_completed_items:
        recent_completed_summary[item["type"]] = recent_completed_summary.get(item["type"], 0) + 1
        recent_completed_summary["SUCCESS"] = recent_completed_summary.get("SUCCESS", 0) + 1
    recent_failed_summary: dict[str, int] = {}
    for item in recent_failed_items:
        recent_failed_summary[item["type"]] = recent_failed_summary.get(item["type"], 0) + 1
        bucket = item.get("mission_bucket")
        if bucket:
            recent_failed_summary[bucket] = recent_failed_summary.get(bucket, 0) + 1
        recent_failed_summary["FAILED"] = recent_failed_summary.get("FAILED", 0) + 1
    collection_summary = {
        "queued": in_progress_summary.get("QUEUED", 0),
        "running": in_progress_summary.get("RUNNING", 0),
        "completed": recent_completed_summary.get("SUCCESS", 0),
        "failed": recent_failed_summary.get("FAILED", 0),
    }
    collection_summary["tracked_total"] = sum(collection_summary.values())

    return {
        "items": items,
        "in_progress_items": in_progress_items,
        "recent_completed_items": recent_completed_items,
        "recent_failed_items": recent_failed_items,
        "summary": summary,
        "in_progress_summary": in_progress_summary,
        "recent_completed_summary": recent_completed_summary,
        "recent_failed_summary": recent_failed_summary,
        "collection_summary": collection_summary,
        "total": len(items),
        "in_progress_total": len(in_progress_items),
        "recent_completed_total": len(recent_completed_items),
        "recent_failed_total": len(recent_failed_items),
        "cooldown_hours": COMPLETED_QUEUE_COOLDOWN_HOURS,
        "generated_at": current_time.isoformat(),
    }


def _queue_job_spec(item: dict[str, Any], organization_id: int | None) -> dict[str, Any] | None:
    item_type = str(item.get("type") or "").upper()
    opportunity = item.get("opportunity") or {}
    opportunity_id = opportunity.get("id")
    if item_type == "AWARDEE_ENRICHMENT_READY" and opportunity_id:
        fingerprint = (item.get("meta") or {}).get("opportunity_fingerprint")
        payload = {
            "opportunity_id": int(opportunity_id),
            "organization_id": organization_id,
            "force": True,
            "opportunity_fingerprint": fingerprint,
        }
        return {"kind": "awardee_enrichment", "payload": payload}
    if item_type == "NSN_INTELLIGENCE_REFRESH":
        nsn = _normalize_nsn((item.get("meta") or {}).get("nsn"))
        if not nsn:
            return None
        fingerprint = (item.get("meta") or {}).get("opportunity_fingerprint")
        payload = {
            "nsn": nsn,
            "run_usaspending": True,
            "seed_providers": True,
            "limit": 50,
            "organization_id": organization_id,
            "opportunity_fingerprint": fingerprint,
        }
        return {"kind": "nsn_build", "payload": payload}
    return None


def _job_signature(kind: str, payload: dict[str, Any]) -> tuple[Any, ...]:
    if kind == "awardee_enrichment":
        return (kind, payload.get("organization_id"), payload.get("opportunity_id"))
    if kind == "nsn_build":
        return (kind, payload.get("organization_id"), _normalize_nsn(payload.get("nsn")))
    return (kind, payload.get("organization_id"), _freeze_signature_value(payload or {}))


def _active_job_signatures(db: Session, organization_id: int | None) -> set[tuple[Any, ...]]:
    query = db.query(SearchJob).filter(SearchJob.status.in_(("queued", "running")))
    query = _scope_org(query, SearchJob, organization_id)
    rows = query.all()
    signatures: set[tuple[Any, ...]] = set()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        signatures.add(_job_signature(row.kind, payload))
    return signatures


def queue_daily_work(db: Session, organization_id: int | None = None, user_id: int | None = None, limit: int = 200) -> dict[str, Any]:
    queue = build_daily_work_queue(db, organization_id=organization_id, user_id=user_id, limit=limit)
    items = list(queue.get("items") or [])
    active_signatures = _active_job_signatures(db, organization_id)
    queued_jobs: list[dict[str, Any]] = []
    skipped_duplicates: list[dict[str, Any]] = []

    for item in items:
        if item.get("type") not in QUEUEABLE_TYPES:
            continue
        spec = _queue_job_spec(item, organization_id)
        if not spec:
            continue
        signature = _job_signature(spec["kind"], spec["payload"])
        if signature in active_signatures:
            skipped_duplicates.append(
                {
                    "item_id": item.get("id"),
                    "type": item.get("type"),
                    "kind": spec["kind"],
                    "target": spec["payload"].get("opportunity_id") or spec["payload"].get("nsn"),
                }
            )
            continue
        spec["payload"]["user_id"] = user_id
        job = start_search_job(spec["kind"], spec["payload"])
        active_signatures.add(signature)
        queued_jobs.append(
            {
                "item_id": item.get("id"),
                "type": item.get("type"),
                "kind": spec["kind"],
                "target": spec["payload"].get("opportunity_id") or spec["payload"].get("nsn"),
                "job_id": job.get("id"),
                "status": job.get("status"),
            }
        )

    result = {
        "status": "ok",
        "organization_id": organization_id,
        "generated_at": queue.get("generated_at"),
        "scanned_items": len(items),
        "queueable_items": sum(1 for item in items if item.get("type") in QUEUEABLE_TYPES),
        "queued_count": len(queued_jobs),
        "skipped_duplicate_count": len(skipped_duplicates),
        "queued_jobs": queued_jobs,
        "skipped_duplicates": skipped_duplicates,
    }
    batch_job = record_search_job(
        "work_queue_batch",
        {
            "organization_id": organization_id,
            "user_id": user_id,
            "limit": limit,
        },
        result=result,
        progress={"completed_steps": result["queued_count"], "total_steps": result["queueable_items"], "percent": 100},
    )
    result["batch_job_id"] = batch_job.get("id")
    return result


def list_daily_queue_runs(db: Session, organization_id: int | None = None, user_id: int | None = None, limit: int = 10) -> dict[str, Any]:
    query = db.query(SearchJob).filter(SearchJob.kind == "work_queue_batch")
    query = _scope_org(query, SearchJob, organization_id)
    if user_id is not None:
        query = query.filter(SearchJob.user_id == user_id)
    rows = query.order_by(desc(SearchJob.created_at), desc(SearchJob.id)).limit(limit).all()
    runs: list[dict[str, Any]] = []
    for row in rows:
        result = row.result if isinstance(row.result, dict) else {}
        runs.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "queued_count": int(result.get("queued_count") or 0),
                "skipped_duplicate_count": int(result.get("skipped_duplicate_count") or 0),
                "queueable_items": int(result.get("queueable_items") or 0),
                "scanned_items": int(result.get("scanned_items") or 0),
                "queued_jobs": list(result.get("queued_jobs") or []),
            }
        )
    return {
        "items": runs,
        "total": len(runs),
        "organization_id": organization_id,
        "user_id": user_id,
    }
