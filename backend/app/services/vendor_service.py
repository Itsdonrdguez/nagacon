from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead, VendorQuote
from app.services.rfq_parser import parse_dibbs_sources


DEFAULT_STATUS = "NOT_REQUESTED"
ALLOWED_STATUSES = {"NOT_REQUESTED", "REQUESTED", "RECEIVED", "NO_BID", "INVALID"}
LEAD_ALLOWED_STATUSES = {"NEW", "REVIEW", "SHORTLISTED", "SEEDED_TO_QUOTES", "IGNORED"}
FOLLOW_UP_BUSINESS_DAYS = 2


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


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
    current_time = now or datetime.utcnow()
    if not getattr(rec, "requested_at", None):
        rec.requested_at = current_time
    if not getattr(rec, "next_follow_up_at", None):
        rec.next_follow_up_at = add_business_days(getattr(rec, "last_follow_up_at", None) or rec.requested_at or current_time, FOLLOW_UP_BUSINESS_DAYS)


def _clear_quote_follow_up_if_terminal(rec: VendorQuote) -> None:
    if str(getattr(rec, "status", "") or "").strip().upper() in {"RECEIVED", "NO_BID", "INVALID", "NOT_REQUESTED"}:
        rec.next_follow_up_at = None


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
        company_name = _clean(s.get("company_name"))
        cage = _clean(s.get("cage"))
        part_number = _clean(s.get("part_number"))
        raw_text = _clean(s.get("raw_text"))
        confidence = 90 if cage and company_name else 80 if cage or company_name else 60 if part_number else 40

        q = db.query(VendorLead).filter(VendorLead.opportunity_id == opp.id)
        if cage:
            q = q.filter(VendorLead.cage == cage)
        else:
            q = q.filter(VendorLead.cage.is_(None))
        if company_name:
            q = q.filter(func.coalesce(VendorLead.company_name, "") == company_name)
        else:
            q = q.filter(VendorLead.company_name.is_(None))
        if part_number:
            q = q.filter(VendorLead.part_number == part_number)
        else:
            q = q.filter(VendorLead.part_number.is_(None))

        rec = q.first()
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
                rec.updated_at = datetime.utcnow()
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

    rec.updated_at = datetime.utcnow()
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
        rec.updated_at = datetime.utcnow()
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
                existing.updated_at = datetime.utcnow()
            if lead.status != "SEEDED_TO_QUOTES":
                lead.status = "SEEDED_TO_QUOTES"
                lead.updated_at = datetime.utcnow()
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
        lead.updated_at = datetime.utcnow()
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


def upsert_quote(db: Session, opportunity_id: int, cage: str, part_number: str | None, patch: dict[str, Any], organization_id: int | None = None) -> VendorQuote:
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
        if rec.status == "REQUESTED":
            _set_quote_requested_follow_up(rec)
        else:
            _clear_quote_follow_up_if_terminal(rec)
    if rec.organization_id is None and organization_id is not None:
        rec.organization_id = organization_id

    rec.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rec)
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
    rec.updated_at = datetime.utcnow()
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


def mark_quote_followed_up(db: Session, opportunity_id: int, quote_id: int, organization_id: int | None = None, notes: str | None = None) -> dict[str, Any]:
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

    now = datetime.utcnow()
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
    return {
        "vendor_quote_id": rec.id,
        "status": rec.status,
        "follow_up_count": rec.follow_up_count,
        "last_follow_up_at": rec.last_follow_up_at,
        "next_follow_up_at": rec.next_follow_up_at,
    }
