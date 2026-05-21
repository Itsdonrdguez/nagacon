from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead, VendorQuote
from app.services.rfq_parser import parse_dibbs_sources
from app.services.workflow_audit import record_workflow_event
from app.utils.utc import utcnow


DEFAULT_STATUS = "NOT_REQUESTED"
ALLOWED_STATUSES = {"NOT_REQUESTED", "REQUESTED", "RECEIVED", "NO_BID", "INVALID"}
LEAD_ALLOWED_STATUSES = {"NEW", "REVIEW", "SHORTLISTED", "SEEDED_TO_QUOTES", "IGNORED"}
FOLLOW_UP_BUSINESS_DAYS = 2


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _clean_limited(v: str | None, max_len: int) -> str | None:
    clean = _clean(v)
    if not clean:
        return None
    return clean[:max_len].strip() or None


def _compact_nsn(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _sanitize_part_number(part_number: str | None, *, nsn: str | None = None) -> str | None:
    clean = _clean(part_number)
    if not clean:
        return None
    compact = _compact_nsn(clean)
    if len(compact) == 13 and nsn and compact == _compact_nsn(nsn):
        return None
    return clean


def _sanitize_company_name(company_name: str | None, *, cage: str | None = None, part_number: str | None = None) -> str | None:
    clean = _clean(company_name)
    if not clean:
        return None
    if cage:
        marker = clean.upper().find(str(cage).upper())
        if marker > 2:
            clean = clean[:marker].strip(" -|,;/")
    if part_number:
        marker = clean.upper().find(str(part_number).upper())
        if marker > 2:
            clean = clean[:marker].strip(" -|,;/")
    clean = " ".join(clean.split())
    return clean[:200].strip() or None


def _find_existing_vendor_lead(
    db: Session,
    *,
    opportunity_id: int,
    organization_id: int | None,
    cage: str | None,
    company_name: str | None,
    part_number: str | None,
) -> VendorLead | None:
    base_query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)
    base_query = _scope_vendor_leads(base_query, organization_id)

    if cage:
        cage_query = base_query.filter(VendorLead.cage == cage)
        if part_number:
            found = cage_query.filter(VendorLead.part_number == part_number).first()
            if found:
                return found
        else:
            found = cage_query.filter(VendorLead.part_number.is_(None)).first()
            if found:
                return found
        fallback = (
            cage_query
            .order_by(VendorLead.part_number.is_(None), VendorLead.confidence.desc().nullslast(), VendorLead.id.desc())
            .first()
        )
        if fallback:
            return fallback

    company_query = base_query
    if company_name:
        company_query = company_query.filter(func.coalesce(VendorLead.company_name, "") == company_name)
    else:
        company_query = company_query.filter(VendorLead.company_name.is_(None))
    if part_number:
        company_query = company_query.filter(VendorLead.part_number == part_number)
    else:
        company_query = company_query.filter(VendorLead.part_number.is_(None))
    return company_query.first()


def _scope_vendor_leads(query, organization_id: int | None):
    if organization_id is not None:
        query = query.filter(
            or_(
                VendorLead.organization_id == organization_id,
                VendorLead.organization_id.is_(None),
            )
        )
    return query


def _scope_vendor_quotes(query, organization_id: int | None):
    if organization_id is not None:
        query = query.filter(
            or_(
                VendorQuote.organization_id == organization_id,
                VendorQuote.organization_id.is_(None),
            )
        )
    return query


def add_business_days(start: datetime, business_days: int) -> datetime:
    current = start
    remaining = max(int(business_days or 0), 0)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _set_quote_requested_follow_up(rec: VendorQuote, now: datetime | None = None) -> None:
    current_time = now or utcnow()
    if not getattr(rec, "requested_at", None):
        rec.requested_at = current_time
    if not getattr(rec, "next_follow_up_at", None):
        rec.next_follow_up_at = add_business_days(getattr(rec, "last_follow_up_at", None) or rec.requested_at or current_time, FOLLOW_UP_BUSINESS_DAYS)


def _clear_quote_follow_up_if_terminal(rec: VendorQuote) -> None:
    if str(getattr(rec, "status", "") or "").strip().upper() in {"RECEIVED", "NO_BID", "INVALID", "NOT_REQUESTED"}:
        rec.next_follow_up_at = None


def build_quote_follow_up_summary(quotes: list[Any], now: datetime | None = None) -> dict[str, Any]:
    current_time = now or utcnow()
    summary: dict[str, Any] = {
        "total": len(quotes),
        "requested": 0,
        "due": 0,
        "scheduled": 0,
        "closed": 0,
        "not_requested": 0,
        "missing_schedule": 0,
        "due_quote_ids": [],
        "next_due_at": None,
    }
    next_due_at = None
    for quote in quotes:
        status = str(getattr(quote, "status", "") or "").strip().upper()
        next_follow_up_at = getattr(quote, "next_follow_up_at", None)
        if status == "REQUESTED":
            summary["requested"] += 1
            if next_follow_up_at and next_follow_up_at <= current_time:
                summary["due"] += 1
                summary["due_quote_ids"].append(getattr(quote, "id", None))
            elif next_follow_up_at:
                summary["scheduled"] += 1
                if next_due_at is None or next_follow_up_at < next_due_at:
                    next_due_at = next_follow_up_at
            else:
                summary["missing_schedule"] += 1
        elif status in {"RECEIVED", "NO_BID", "INVALID"}:
            summary["closed"] += 1
        else:
            summary["not_requested"] += 1

    summary["due_quote_ids"] = [quote_id for quote_id in summary["due_quote_ids"] if quote_id is not None]
    summary["next_due_at"] = next_due_at
    return summary


def sync_vendor_leads_from_parsed(db: Session, opp: Opportunity) -> dict[str, int]:
    parsed = getattr(opp, "parsed_json", None) or {}
    if not parsed and getattr(opp, "raw_text", None):
        parsed = parse_dibbs_sources(opp.raw_text or "", opp.url)
        opp.parsed_json = parsed
        db.commit()

    nsn = _clean(parsed.get("nsn"))
    sources = parsed.get("approved_sources") or []
    created = 0
    updated = 0

    for s in sources:
        cage = _clean_limited(s.get("cage"), 10)
        part_number = _sanitize_part_number(s.get("part_number"), nsn=nsn)
        company_name = _sanitize_company_name(s.get("company_name"), cage=cage, part_number=part_number)
        raw_text = _clean(s.get("raw_text"))
        confidence = 90 if cage and company_name else 80 if cage or company_name else 60 if part_number else 40

        rec = _find_existing_vendor_lead(
            db,
            opportunity_id=opp.id,
            organization_id=getattr(opp, "organization_id", None),
            cage=cage,
            company_name=company_name,
            part_number=part_number,
        )
        if rec:
            touched = False
            if rec.organization_id is None and getattr(opp, "organization_id", None) is not None:
                rec.organization_id = getattr(opp, "organization_id", None)
                touched = True
            if not rec.nsn and nsn:
                rec.nsn = nsn
                touched = True
            if company_name and not rec.company_name:
                rec.company_name = company_name
                touched = True
            if cage and not rec.cage:
                rec.cage = cage
                touched = True
            if part_number and not rec.part_number:
                rec.part_number = part_number
                touched = True
            if raw_text and not rec.raw_text:
                rec.raw_text = raw_text
                touched = True
            if confidence > (rec.confidence or 0):
                rec.confidence = confidence
                touched = True
            if touched:
                rec.updated_at = utcnow()
                updated += 1
            continue

        db.add(VendorLead(
            organization_id=getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            source_type="APPROVED_SOURCE",
            company_name=company_name,
            cage=cage,
            part_number=part_number,
            nsn=nsn,
            status="NEW",
            confidence=confidence,
            is_approved_source=True,
            raw_text=raw_text,
        ))
        created += 1

    if created or updated:
        db.commit()

    return {
        "created": created,
        "updated": updated,
        "approved_source_count": len(sources),
    }


def list_vendor_leads(db: Session, opportunity_id: int, organization_id: int | None = None) -> list[VendorLead]:
    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)
    query = _scope_vendor_leads(query, organization_id)
    return (
        query
        .order_by(VendorLead.confidence.desc(), VendorLead.company_name.asc().nullslast(), VendorLead.cage.asc().nullslast(), VendorLead.part_number.asc().nullslast())
        .all()
    )


def update_vendor_lead(db: Session, opportunity_id: int, lead_id: int, patch: dict[str, Any], organization_id: int | None = None) -> VendorLead:
    rec = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .filter(VendorLead.id == lead_id)
    )
    rec = _scope_vendor_leads(rec, organization_id)
    rec = rec.first()
    if not rec:
        raise ValueError("vendor lead not found")

    if "status" in patch and patch["status"]:
        st = str(patch["status"]).strip().upper()
        rec.status = st if st in LEAD_ALLOWED_STATUSES else rec.status
    if "notes" in patch:
        rec.notes = patch["notes"]
    if rec.organization_id is None and organization_id is not None:
        rec.organization_id = organization_id

    rec.updated_at = utcnow()
    db.commit()
    db.refresh(rec)
    return rec


def promote_vendor_lead_to_quote_request(db: Session, opportunity_id: int, lead_id: int, organization_id: int | None = None) -> dict[str, Any]:
    rec = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .filter(VendorLead.id == lead_id)
    )
    rec = _scope_vendor_leads(rec, organization_id)
    rec = rec.first()
    if not rec:
        raise ValueError("vendor lead not found")

    touched = False
    if rec.organization_id is None and organization_id is not None:
        rec.organization_id = organization_id
        touched = True
    if rec.status not in {"SHORTLISTED", "SEEDED_TO_QUOTES"}:
        rec.status = "SHORTLISTED"
        touched = True
    if touched:
        rec.updated_at = utcnow()
        db.add(rec)
        db.commit()
        db.refresh(rec)

    return {
        "lead_id": rec.id,
        "company_name": rec.company_name,
        "cage": rec.cage,
        "status": rec.status,
        "notes": rec.notes,
    }


def seed_quotes_from_parsed(db: Session, opp: Opportunity) -> dict[str, int]:
    lead_stats = sync_vendor_leads_from_parsed(db, opp)
    leads = list_vendor_leads(db, opp.id, organization_id=getattr(opp, "organization_id", None))
    created = 0
    shortlisted = 0

    for lead in leads:
        cage = _clean(lead.cage)
        if not cage:
            continue
        shortlisted += 1
        part_number = _clean(lead.part_number)
        company_name = _clean(lead.company_name)

        q = (
            db.query(VendorQuote)
            .filter(VendorQuote.opportunity_id == opp.id)
            .filter(VendorQuote.cage == cage)
        )
        q = _scope_vendor_quotes(q, getattr(opp, "organization_id", None))
        if part_number is None:
            q = q.filter(VendorQuote.part_number.is_(None))
        else:
            q = q.filter(VendorQuote.part_number == part_number)

        existing = q.first()
        if existing:
            touched = False
            if existing.organization_id is None and getattr(opp, "organization_id", None) is not None:
                existing.organization_id = getattr(opp, "organization_id", None)
                touched = True
            if (not existing.company_name) and company_name:
                existing.company_name = company_name
                touched = True
            if touched:
                existing.updated_at = utcnow()
            if lead.status != "SEEDED_TO_QUOTES":
                lead.status = "SEEDED_TO_QUOTES"
                lead.updated_at = utcnow()
            continue

        db.add(VendorQuote(
            organization_id=getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            cage=cage,
            company_name=company_name,
            part_number=part_number,
            status=DEFAULT_STATUS,
        ))
        lead.status = "SEEDED_TO_QUOTES"
        lead.updated_at = utcnow()
        created += 1

    if created or shortlisted or lead_stats.get("created") or lead_stats.get("updated"):
        db.commit()

    return {
        "created": created,
        "lead_created": lead_stats.get("created", 0),
        "lead_updated": lead_stats.get("updated", 0),
        "lead_count": len(leads),
        "seedable_count": shortlisted,
        "approved_source_count": lead_stats.get("approved_source_count", 0),
    }


def list_quotes(db: Session, opportunity_id: int, organization_id: int | None = None) -> list[VendorQuote]:
    query = db.query(VendorQuote).filter(VendorQuote.opportunity_id == opportunity_id)
    query = _scope_vendor_quotes(query, organization_id)
    return (
        query
        .order_by(VendorQuote.company_name.asc().nullslast(), VendorQuote.cage.asc(), VendorQuote.part_number.asc().nullslast())
        .all()
    )


def upsert_quote(
    db: Session,
    opportunity_id: int,
    cage: str,
    part_number: str | None,
    patch: dict[str, Any],
    organization_id: int | None = None,
    user_id: int | None = None,
) -> VendorQuote:
    cage = cage.strip()
    if not cage:
        raise ValueError("cage required")

    q = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opportunity_id)
        .filter(VendorQuote.cage == cage)
    )
    q = _scope_vendor_quotes(q, organization_id)

    if part_number is None or str(part_number).strip() == "":
        part_db = None
        q = q.filter(VendorQuote.part_number.is_(None))
    else:
        part_db = str(part_number).strip()
        q = q.filter(VendorQuote.part_number == part_db)

    rec = q.first()
    if not rec:
        opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
        rec = VendorQuote(
            organization_id=getattr(opp, "organization_id", None),
            opportunity_id=opportunity_id,
            cage=cage,
            part_number=part_db,
            status=DEFAULT_STATUS,
        )
        db.add(rec)
        db.flush()
    previous_status = str(getattr(rec, "status", DEFAULT_STATUS) or DEFAULT_STATUS).strip().upper()

    for k in ["company_name", "contact_name", "email", "phone", "notes"]:
        if k in patch:
            setattr(rec, k, patch[k])

    if "unit_price" in patch:
        rec.unit_price = patch["unit_price"]
    if "lead_time_days" in patch:
        rec.lead_time_days = patch["lead_time_days"]

    if "status" in patch and patch["status"]:
        st = str(patch["status"]).strip().upper()
        rec.status = st if st in ALLOWED_STATUSES else DEFAULT_STATUS
        if rec.status == "REQUESTED" and not any([rec.email, rec.phone, rec.contact_name, rec.company_name]):
            raise ValueError("quote request requires vendor contact information before status can be REQUESTED")
        if rec.status == "RECEIVED" and rec.unit_price is None:
            raise ValueError("received quotes require a unit_price")
        if rec.status == "RECEIVED" and previous_status not in {"REQUESTED", "RECEIVED"} and not bool(patch.get("approved")):
            raise ValueError("explicit approval is required before marking a quote as RECEIVED without a prior REQUESTED state")
        if rec.status == "REQUESTED":
            if not bool(patch.get("approved")):
                raise ValueError("explicit approval is required before marking a quote request as REQUESTED")
            _set_quote_requested_follow_up(rec)
        else:
            _clear_quote_follow_up_if_terminal(rec)
    if rec.organization_id is None and organization_id is not None:
        rec.organization_id = organization_id

    rec.updated_at = utcnow()
    db.commit()
    db.refresh(rec)
    if rec.status != previous_status:
        record_workflow_event(
            db,
            opportunity_id=opportunity_id,
            organization_id=organization_id or rec.organization_id,
            user_id=user_id,
            entity_type="vendor_quote",
            entity_id=rec.id,
            action="status_transition",
            from_state=previous_status,
            to_state=rec.status,
            metadata={
                "cage": rec.cage,
                "part_number": rec.part_number,
                "unit_price": float(rec.unit_price) if rec.unit_price is not None else None,
                "approved": bool(patch.get("approved")),
                "approval_notes": patch.get("approval_notes"),
            },
        )
    return rec


def sync_quote_status_from_outreach_artifact(db: Session, artifact: Any, action: str | None, organization_id: int | None = None) -> dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    content = getattr(artifact, "content_json", None) or {}
    quote_id = content.get("vendor_quote_id")
    if normalized_action != "sent":
        return {"updated": False, "reason": "action_not_sent"}
    if not quote_id:
        return {"updated": False, "reason": "missing_vendor_quote_id"}

    query = (
        db.query(VendorQuote)
        .filter(VendorQuote.id == quote_id)
        .filter(VendorQuote.opportunity_id == getattr(artifact, "opportunity_id", None))
    )
    query = _scope_vendor_quotes(query, organization_id)
    rec = query.first()
    if not rec:
        return {"updated": False, "reason": "quote_not_found", "vendor_quote_id": quote_id}

    if rec.status and str(rec.status).strip().upper() != DEFAULT_STATUS:
        return {
            "updated": False,
            "reason": "status_already_set",
            "vendor_quote_id": rec.id,
            "status": rec.status,
        }

    rec.status = "REQUESTED"
    _set_quote_requested_follow_up(rec)
    rec.updated_at = utcnow()
    note = f"Outreach sent from workspace artifact {getattr(artifact, 'id', None)}."
    existing_notes = str(rec.notes or "").strip()
    if note not in existing_notes:
        rec.notes = f"{existing_notes}\n{note}".strip() if existing_notes else note
    db.add(rec)
    return {
        "updated": True,
        "vendor_quote_id": rec.id,
        "status": rec.status,
    }


def mark_quote_followed_up(
    db: Session,
    opportunity_id: int,
    quote_id: int,
    organization_id: int | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    query = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opportunity_id)
        .filter(VendorQuote.id == quote_id)
    )
    query = _scope_vendor_quotes(query, organization_id)
    rec = query.first()
    if not rec:
        raise ValueError("vendor quote not found")

    if str(rec.status or "").strip().upper() != "REQUESTED":
        raise ValueError("follow-up can only be logged for requested quotes")

    now = utcnow()
    if not rec.requested_at:
        rec.requested_at = now
    rec.last_follow_up_at = now
    rec.next_follow_up_at = add_business_days(now, FOLLOW_UP_BUSINESS_DAYS)
    rec.follow_up_count = int(rec.follow_up_count or 0) + 1
    rec.updated_at = now

    note = notes or f"Follow-up logged on {now.date().isoformat()}."
    existing_notes = str(rec.notes or "").strip()
    if note and note not in existing_notes:
        rec.notes = f"{existing_notes}\n{note}".strip() if existing_notes else note

    db.add(rec)
    db.commit()
    db.refresh(rec)
    record_workflow_event(
        db,
        opportunity_id=opportunity_id,
        organization_id=organization_id or rec.organization_id,
        user_id=user_id,
        entity_type="vendor_quote",
        entity_id=rec.id,
        action="follow_up_logged",
        from_state=rec.status,
        to_state=rec.status,
        notes=notes,
        metadata={"follow_up_count": rec.follow_up_count},
    )
    return {
        "vendor_quote_id": rec.id,
        "status": rec.status,
        "follow_up_count": rec.follow_up_count,
        "last_follow_up_at": rec.last_follow_up_at,
        "next_follow_up_at": rec.next_follow_up_at,
    }
