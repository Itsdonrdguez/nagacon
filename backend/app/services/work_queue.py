from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact


HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"


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


def _count_by_opportunity(db: Session, model, organization_id: int | None, artifact_type: str | None = None) -> dict[int, int]:
    query = db.query(model.opportunity_id, func.count(model.id))
    query = _scope_org(query, model, organization_id)
    if artifact_type and hasattr(model, "artifact_type"):
        query = query.filter(model.artifact_type == artifact_type)
    rows = query.group_by(model.opportunity_id).all()
    return {int(opp_id): int(count) for opp_id, count in rows}


def build_daily_work_queue(db: Session, organization_id: int | None = None, limit: int = 200, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.utcnow()

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

    submissions_query = db.query(BidSubmission).filter(BidSubmission.opportunity_id.in_(opp_ids))
    submissions = {row.opportunity_id: row for row in submissions_query.all()}

    quote_query = db.query(VendorQuote).filter(VendorQuote.opportunity_id.in_(opp_ids))
    quote_query = _scope_org(quote_query, VendorQuote, organization_id)
    quotes = quote_query.all()

    recent_awardee_jobs_query = db.query(SearchJob).filter(SearchJob.kind == "awardee_enrichment")
    recent_awardee_jobs_query = _scope_org(recent_awardee_jobs_query, SearchJob, organization_id)
    recent_awardee_jobs = recent_awardee_jobs_query.all()
    awardee_job_opp_ids = set()
    for job in recent_awardee_jobs:
        if not isinstance(job.payload, dict) or not (job.payload or {}).get("opportunity_id"):
            continue
        try:
            awardee_job_opp_ids.add(int((job.payload or {}).get("opportunity_id")))
        except (TypeError, ValueError):
            continue

    items: list[dict[str, Any]] = []

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
        days_left = _days_until(opp.due_at, current_time)
        is_open = days_left is None or days_left >= 0
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
                meta={"lead_count": 0},
            ))

        nsn = _extract_nsn(opp)
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

        if is_open and quote_counts.get(opp.id, 0) > 0 and submission_package_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "MISSING_SUBMISSION_PACKAGE",
                LOW,
                opp,
                "Build submission package",
                "Quote records exist, but no submission package artifact has been saved.",
                meta={"quote_count": quote_counts.get(opp.id, 0)},
            ))

        submission = submissions.get(opp.id)
        if days_left is not None and days_left < 0 and opp.id not in awardee_job_opp_ids:
            items.append(_item(
                "AWARDEE_ENRICHMENT_READY",
                LOW,
                opp,
                "Check awardee enrichment",
                "Solicitation is closed. Use it to improve awardee and vendor intelligence.",
                action_label="Open Closed Intelligence",
                meta={"submission_status": getattr(submission, "status", None), "days_since_close": abs(days_left)},
            ))

        if nsn and nsn_artifact_counts.get(opp.id, 0) == 0:
            items.append(_item(
                "NSN_INTELLIGENCE_REFRESH",
                LOW,
                opp,
                "Refresh NSN intelligence",
                f"NSN {nsn} has no saved intelligence artifact yet.",
                action_label="Open NSN Intelligence",
                meta={"nsn": nsn},
            ))

    priority_order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    items.sort(key=lambda item: (priority_order.get(item["priority"], 9), item.get("due_at") or "9999", item["type"]))
    summary: dict[str, int] = {}
    for item in items:
        summary[item["type"]] = summary.get(item["type"], 0) + 1
        summary[item["priority"]] = summary.get(item["priority"], 0) + 1

    return {
        "items": items,
        "summary": summary,
        "total": len(items),
        "generated_at": current_time.isoformat(),
    }
