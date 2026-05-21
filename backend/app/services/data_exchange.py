from __future__ import annotations

import csv
import io
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead, VendorQuote
from app.repositories.opportunities import OpportunityRepository
from app.repositories.providers import ProviderRepository
from app.services.vendor_service import list_quotes
from app.services.work_queue import build_daily_work_queue


def _csv_response(rows: Iterable[dict], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def export_providers_csv(db: Session, organization_id: int | None = None, limit: int = 1000) -> str:
    rows, _ = ProviderRepository(db, organization_id=organization_id).list_rows(limit=limit, offset=0)
    fieldnames = [
        "provider_id",
        "company_name",
        "cage",
        "uei",
        "website",
        "email",
        "phone",
        "canonical_name",
        "identity_source",
        "identity_confidence",
        "nsn",
        "fsc",
        "nomenclature",
        "relationship_type",
        "source",
        "confidence",
    ]
    return _csv_response(rows, fieldnames)


def export_quotes_csv(db: Session, opportunity_id: int, organization_id: int | None = None) -> str:
    rows = []
    for quote in list_quotes(db, opportunity_id, organization_id=organization_id):
        rows.append({
            "quote_id": quote.id,
            "opportunity_id": quote.opportunity_id,
            "company_name": quote.company_name,
            "cage": quote.cage,
            "part_number": quote.part_number,
            "email": quote.email,
            "phone": quote.phone,
            "status": quote.status,
            "unit_price": quote.unit_price,
            "lead_time_days": quote.lead_time_days,
            "requested_at": quote.requested_at,
            "last_follow_up_at": quote.last_follow_up_at,
            "next_follow_up_at": quote.next_follow_up_at,
            "follow_up_count": quote.follow_up_count,
            "notes": quote.notes,
        })
    return _csv_response(rows, [
        "quote_id",
        "opportunity_id",
        "company_name",
        "cage",
        "part_number",
        "email",
        "phone",
        "status",
        "unit_price",
        "lead_time_days",
        "requested_at",
        "last_follow_up_at",
        "next_follow_up_at",
        "follow_up_count",
        "notes",
    ])


def export_work_queue_csv(db: Session, organization_id: int | None = None) -> str:
    queue = build_daily_work_queue(db, organization_id=organization_id)
    rows = []
    for item in queue.get("items", []):
        opp = item.get("opportunity") or {}
        rows.append({
            "item_id": item.get("id"),
            "type": item.get("type"),
            "priority": item.get("priority"),
            "title": item.get("title"),
            "subtitle": item.get("subtitle"),
            "solicitation_number": opp.get("solicitation_number"),
            "source": opp.get("source"),
            "agency": opp.get("agency"),
            "due_at": item.get("due_at"),
            "action_url": item.get("action_url"),
        })
    return _csv_response(rows, [
        "item_id",
        "type",
        "priority",
        "title",
        "subtitle",
        "solicitation_number",
        "source",
        "agency",
        "due_at",
        "action_url",
    ])


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_pairs(pairs: list[tuple[str | None, str | None]]) -> list[tuple[str | None, str | None]]:
    result: list[tuple[str | None, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for part_number, company_name in pairs:
        clean_part = _clean(part_number)
        clean_company = _clean(company_name)
        key = ((clean_part or "").upper(), (clean_company or "").upper())
        if key in seen:
            continue
        seen.add(key)
        result.append((clean_part, clean_company))
    return result


def export_opportunities_csv(
    db: Session,
    *,
    organization_id: int | None = None,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    agency: str | None = None,
    state: str | None = None,
    naics_codes: list[str] | None = None,
    fsc_codes: list[str] | None = None,
    limit: int = 2000,
) -> str:
    repo = OpportunityRepository(db, organization_id=organization_id)
    query = repo._apply_filters(
        repo._scoped_query(),
        q=q,
        source=source,
        set_aside_type=set_aside_type,
        due_window=due_window,
        nsn=nsn,
        agency=agency,
        state=state,
        naics_codes=naics_codes,
        fsc_codes=fsc_codes,
    )
    opportunities = (
        query
        .order_by(Opportunity.id.desc())
        .limit(limit)
        .all()
    )
    opportunity_ids = [opp.id for opp in opportunities if getattr(opp, "id", None) is not None]

    leads_by_opp: dict[int, list[VendorLead]] = {}
    quotes_by_opp: dict[int, list[VendorQuote]] = {}
    submissions_by_opp: dict[int, BidSubmission] = {}
    if opportunity_ids:
        lead_query = db.query(VendorLead).filter(VendorLead.opportunity_id.in_(opportunity_ids))
        quote_query = db.query(VendorQuote).filter(VendorQuote.opportunity_id.in_(opportunity_ids))
        submission_query = db.query(BidSubmission).filter(BidSubmission.opportunity_id.in_(opportunity_ids))
        if organization_id is not None:
            lead_query = lead_query.filter((VendorLead.organization_id == organization_id) | (VendorLead.organization_id.is_(None)))
            quote_query = quote_query.filter((VendorQuote.organization_id == organization_id) | (VendorQuote.organization_id.is_(None)))
        for lead in lead_query.all():
            leads_by_opp.setdefault(int(lead.opportunity_id), []).append(lead)
        for quote in quote_query.all():
            quotes_by_opp.setdefault(int(quote.opportunity_id), []).append(quote)
        for submission in submission_query.all():
            submissions_by_opp[int(submission.opportunity_id)] = submission

    rows: list[dict[str, str]] = []
    for opp in opportunities:
        parsed = opp.parsed_json if isinstance(getattr(opp, "parsed_json", None), dict) else {}
        explicit_pairs: list[tuple[str | None, str | None]] = []

        for source_row in parsed.get("approved_sources") or []:
            if isinstance(source_row, dict):
                explicit_pairs.append((source_row.get("part_number"), source_row.get("company_name")))

        for lead in leads_by_opp.get(int(opp.id), []):
            explicit_pairs.append((getattr(lead, "part_number", None), getattr(lead, "company_name", None)))

        quotes_for_opp = quotes_by_opp.get(int(opp.id), [])
        quotes_by_id = {int(quote.id): quote for quote in quotes_for_opp if getattr(quote, "id", None) is not None}
        for quote in quotes_for_opp:
            explicit_pairs.append((getattr(quote, "part_number", None), getattr(quote, "company_name", None)))

        submission = submissions_by_opp.get(int(opp.id))
        if submission:
            planned_quote = quotes_by_id.get(int(submission.planned_vendor_quote_id)) if getattr(submission, "planned_vendor_quote_id", None) else None
            submission_pairs = [
                (getattr(planned_quote, "part_number", None), getattr(submission, "planned_vendor_name", None)),
                (None, getattr(submission, "submitted_vendor_name", None)),
                (None, getattr(submission, "winning_vendor_name", None)),
            ]
            explicit_pairs.extend(submission_pairs)

        pairs = _unique_pairs(explicit_pairs)
        fallback_parts = [
            _clean(value)
            for value in (parsed.get("part_numbers") or [])
            if _clean(value)
        ]
        fallback_parts = list(dict.fromkeys(fallback_parts))

        if not pairs and fallback_parts:
            pairs = [(part_number, None) for part_number in fallback_parts]
        if not pairs:
            pairs = [(None, None)]

        due_value = opp.due_at.isoformat() if getattr(opp, "due_at", None) else ""
        solicitation = _clean(getattr(opp, "solicitation_number", None)) or str(getattr(opp, "id", ""))
        for part_number, company_name in pairs:
            rows.append({
                "solicitation": solicitation,
                "part_number": part_number or "",
                "company": company_name or "",
                "due_date": due_value,
            })

    return _csv_response(rows, ["solicitation", "part_number", "company", "due_date"])
