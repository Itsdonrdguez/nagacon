from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.opportunity import Opportunity
from app.models.provider import Provider, ProviderItem
from app.models.vendor import VendorLead
from app.schemas.vendor import FollowUpRequest, VendorLeadOut, VendorLeadUpsertRequest, VendorQuoteOut, SeedRequest, UpsertRequest
from app.services.vendor_service import (
    build_quote_follow_up_summary,
    list_quotes,
    mark_quote_followed_up,
    seed_quotes_from_parsed,
    sync_vendor_leads_from_parsed,
    update_vendor_lead,
    upsert_quote,
)
from app.services.providers.pdf_cage_extractor import seed_vendor_leads_from_providers
from app.services.workspace_service import ensure_parsed


router = APIRouter(prefix="/api/vendors", tags=["vendors"])


def _source_label(lead: VendorLead, provider_item: ProviderItem | None = None) -> str:
    source = (lead.source_type or "").upper()
    relationship = (getattr(provider_item, "relationship_type", None) or "").upper()
    if lead.is_approved_source or "APPROVED" in source or "APPROVED" in relationship:
        return "Approved Source"
    if "NSN" in source:
        return "Exact NSN Match"
    if "PART_FINDER_PROVIDER_AWARDEE" in source:
        return "Part Finder Provider + Awardee"
    if "PART_FINDER_PROVIDER" in source:
        return "Part Finder Provider"
    if "PART_FINDER_AWARDEE" in source:
        return "Part Finder Awardee"
    if "USASPENDING" in source or "AWARDEE" in source:
        return "Past Awardee"
    if provider_item is not None:
        return provider_item.relationship_type or "Provider"
    return "Vendor Lead"


def _serialize_leads_with_provider_context(db: Session, leads: list[VendorLead]) -> list[dict]:
    cages = sorted({(lead.cage or "").upper() for lead in leads if lead.cage})
    providers_by_cage: dict[str, Provider] = {}
    items_by_provider_id: dict[int, list[ProviderItem]] = {}
    if cages:
        providers = db.query(Provider).filter(Provider.cage.in_(cages)).all()
        providers_by_cage = {(provider.cage or "").upper(): provider for provider in providers if provider.cage}
        provider_ids = [provider.id for provider in providers]
        if provider_ids:
            items = (
                db.query(ProviderItem)
                .filter(ProviderItem.provider_id.in_(provider_ids))
                .order_by(ProviderItem.confidence.desc().nullslast(), ProviderItem.updated_at.desc())
                .all()
            )
            for item in items:
                items_by_provider_id.setdefault(item.provider_id, []).append(item)

    grouped: dict[tuple[str, str], dict] = {}

    def merge_rows(existing: dict, row: dict) -> dict:
        if int(row.get("confidence") or 0) > int(existing.get("confidence") or 0):
            existing["confidence"] = row.get("confidence")
        if not existing.get("company_name") and row.get("company_name"):
            existing["company_name"] = row.get("company_name")
        if not existing.get("part_number") and row.get("part_number"):
            existing["part_number"] = row.get("part_number")
        if not existing.get("provider_website") and row.get("provider_website"):
            existing["provider_website"] = row.get("provider_website")
        if not existing.get("provider_email") and row.get("provider_email"):
            existing["provider_email"] = row.get("provider_email")
        if not existing.get("provider_phone") and row.get("provider_phone"):
            existing["provider_phone"] = row.get("provider_phone")
        if row.get("is_approved_source"):
            existing["is_approved_source"] = True
        source_bits = [item for item in [existing.get("source_type"), row.get("source_type")] if item]
        existing["source_type"] = "+".join(sorted(dict.fromkeys(source_bits)))
        label_bits = [item for item in [existing.get("source_label"), row.get("source_label")] if item]
        existing["source_label"] = " | ".join(dict.fromkeys(label_bits))
        notes_bits = [item for item in [existing.get("notes"), row.get("notes")] if item]
        existing["notes"] = " | ".join(dict.fromkeys(notes_bits))[:4000] if notes_bits else existing.get("notes")
        raw_bits = [item for item in [existing.get("raw_text"), row.get("raw_text")] if item]
        existing["raw_text"] = " | ".join(dict.fromkeys(raw_bits))[:4000] if raw_bits else existing.get("raw_text")
        if row.get("updated_at") and existing.get("updated_at") and row["updated_at"] > existing["updated_at"]:
            existing["updated_at"] = row["updated_at"]
        return existing

    for lead in leads:
        provider = providers_by_cage.get((lead.cage or "").upper())
        provider_item = None
        if provider:
            items = items_by_provider_id.get(provider.id, [])
            provider_item = next((item for item in items if lead.nsn and item.nsn == lead.nsn), None) or (items[0] if items else None)
        row = VendorLeadOut.model_validate(lead).model_dump()
        row.update({
            "source_label": _source_label(lead, provider_item),
            "provider_website": getattr(provider, "website", None),
            "provider_email": getattr(provider, "email", None),
            "provider_phone": getattr(provider, "phone", None),
            "provider_relationship_type": getattr(provider_item, "relationship_type", None),
            "provider_item": getattr(provider_item, "nomenclature", None),
        })
        cage_key = str(row.get("cage") or "").strip().upper()
        part_key = str(row.get("part_number") or "").strip().upper()
        company_key = str(row.get("company_name") or "").strip().upper()
        identity_key = cage_key or company_key
        if not identity_key:
            continue
        dedupe_key = (identity_key, part_key)
        blank_key = (identity_key, "")
        if part_key and blank_key in grouped:
            merged = merge_rows(grouped.pop(blank_key), row)
            grouped[dedupe_key] = merged
            continue
        if not part_key:
            existing_key = next((key for key in grouped if key[0] == identity_key and key[1]), None)
            if existing_key:
                grouped[existing_key] = merge_rows(grouped[existing_key], row)
                continue
        existing = grouped.get(dedupe_key)
        if not existing:
            grouped[dedupe_key] = row
            continue
        grouped[dedupe_key] = merge_rows(existing, row)
    return list(grouped.values())


def _serialize_quote(quote) -> dict:
    row = VendorQuoteOut.model_validate(quote).model_dump()
    status = str(row.get("status") or "").upper()
    next_follow_up_at = row.get("next_follow_up_at")
    follow_up_due = False
    follow_up_status = None
    follow_up_label = None
    if status == "REQUESTED":
        if next_follow_up_at:
            follow_up_due = next_follow_up_at <= datetime.utcnow()
            follow_up_status = "DUE" if follow_up_due else "SCHEDULED"
            follow_up_label = (
                "Follow up now"
                if follow_up_due
                else f"Follow up {next_follow_up_at.date().isoformat()}"
            )
        else:
            follow_up_status = "MISSING_SCHEDULE"
            follow_up_label = "Follow-up schedule missing"
    elif status in {"RECEIVED", "NO_BID", "INVALID"}:
        follow_up_status = "CLOSED"
        follow_up_label = "No follow-up needed"
    else:
        follow_up_status = "NOT_REQUESTED"
        follow_up_label = "Request not sent"

    row.update({
        "follow_up_due": follow_up_due,
        "follow_up_status": follow_up_status,
        "follow_up_label": follow_up_label,
    })
    return row


def _dedupe_quotes(quotes: list) -> list:
    grouped: dict[tuple[str, str], dict] = {}
    for quote in quotes:
        row = _serialize_quote(quote)
        dedupe_key = (
            str(row.get("cage") or "").strip().upper(),
            str(row.get("part_number") or "").strip().upper(),
        )
        blank_key = (dedupe_key[0], "")
        if dedupe_key[1] and blank_key in grouped:
            grouped[dedupe_key] = grouped.pop(blank_key)
        elif not dedupe_key[1]:
            existing_key = next((key for key in grouped if key[0] == dedupe_key[0] and key[1]), None)
            if existing_key:
                dedupe_key = existing_key
        existing = grouped.get(dedupe_key)
        if not existing:
            grouped[dedupe_key] = row
            continue
        if str(row.get("status") or "").upper() == "RECEIVED" and str(existing.get("status") or "").upper() != "RECEIVED":
            grouped[dedupe_key] = row
            existing = grouped[dedupe_key]
        if row.get("unit_price") is not None and existing.get("unit_price") is None:
            existing["unit_price"] = row.get("unit_price")
        if row.get("lead_time_days") is not None and existing.get("lead_time_days") is None:
            existing["lead_time_days"] = row.get("lead_time_days")
        if not existing.get("company_name") and row.get("company_name"):
            existing["company_name"] = row.get("company_name")
        if not existing.get("contact_name") and row.get("contact_name"):
            existing["contact_name"] = row.get("contact_name")
        if not existing.get("email") and row.get("email"):
            existing["email"] = row.get("email")
        if not existing.get("phone") and row.get("phone"):
            existing["phone"] = row.get("phone")
        note_bits = [item for item in [existing.get("notes"), row.get("notes")] if item]
        existing["notes"] = " | ".join(dict.fromkeys(note_bits))[:4000] if note_bits else existing.get("notes")
        if row.get("updated_at") and existing.get("updated_at") and row["updated_at"] > existing["updated_at"]:
            existing["updated_at"] = row["updated_at"]
    return list(grouped.values())


@router.get("/leads", response_model=list[VendorLeadOut])
def get_leads(
    opportunity_id: int,
    include_suppressed: bool = Query(False),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    org_id = getattr(current_org, "id", None)
    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)
    if org_id is not None:
        query = query.filter(
            or_(
                VendorLead.organization_id == org_id,
                VendorLead.organization_id.is_(None),
            )
        )

    if not include_suppressed:
        query = query.filter(VendorLead.status != "SUPPRESSED")

    leads = query.order_by(VendorLead.id.desc()).all()
    return _serialize_leads_with_provider_context(db, leads)


@router.post("/leads/sync")
def sync_leads(
    req: SeedRequest,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    org_id = getattr(current_org, "id", None)
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id)
    if org_id is not None:
        opp = opp.filter(Opportunity.organization_id == org_id)
    opp = opp.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    out = sync_vendor_leads_from_parsed(db, opp)
    provider_sync = seed_vendor_leads_from_providers(
        db,
        opp,
        parsed=parsed,
        organization_id=org_id,
        user_id=getattr(current_user, "id", None),
    )
    out["cage_count"] = len(parsed.get("cage_codes") or [])
    out["text_source"] = parsed.get("text_source") or {}
    out["provider_sync"] = provider_sync
    return out


@router.post("/leads/upsert", response_model=VendorLeadOut)
def upsert_lead(req: VendorLeadUpsertRequest, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    if req.lead_id is None:
        raise HTTPException(status_code=400, detail="lead_id required")
    patch = req.model_dump(exclude={"opportunity_id", "lead_id"}, exclude_none=False)
    try:
        rec = update_vendor_lead(db, req.opportunity_id, req.lead_id, patch, organization_id=getattr(current_org, "id", None))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return rec


@router.get("/quotes", response_model=list[VendorQuoteOut])
def get_quotes(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return _dedupe_quotes(list_quotes(db, opportunity_id, organization_id=getattr(current_org, "id", None)))


@router.get("/quotes/follow-ups/summary")
def get_quote_follow_up_summary(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    quotes = list_quotes(db, opportunity_id, organization_id=getattr(current_org, "id", None))
    summary = build_quote_follow_up_summary(quotes)
    next_due_at = summary.get("next_due_at")
    return {
        **summary,
        "next_due_at": next_due_at.isoformat() if next_due_at else None,
    }


@router.post("/quotes/seed")
def seed_quotes(
    req: SeedRequest,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    org_id = getattr(current_org, "id", None)
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id)
    if org_id is not None:
        opp = opp.filter(Opportunity.organization_id == org_id)
    opp = opp.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    provider_sync = seed_vendor_leads_from_providers(
        db,
        opp,
        parsed=parsed,
        organization_id=org_id,
        user_id=getattr(current_user, "id", None),
    )
    out = seed_quotes_from_parsed(db, opp)
    out["provider_sync"] = provider_sync
    out["text_source"] = parsed.get("text_source") or {}
    return out


@router.post("/quotes/upsert", response_model=VendorQuoteOut)
def upsert(req: UpsertRequest, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    patch = req.model_dump(exclude={"opportunity_id", "cage", "part_number"}, exclude_none=True)
    try:
        rec = upsert_quote(db, req.opportunity_id, req.cage, req.part_number, patch, organization_id=getattr(current_org, "id", None))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize_quote(rec)


@router.post("/quotes/{quote_id}/follow-up", response_model=VendorQuoteOut)
def log_quote_follow_up(
    quote_id: int,
    req: FollowUpRequest,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    try:
        mark_quote_followed_up(
            db,
            req.opportunity_id,
            quote_id,
            organization_id=getattr(current_org, "id", None),
            notes=req.notes,
        )
        rec = next(
            quote for quote in list_quotes(db, req.opportunity_id, organization_id=getattr(current_org, "id", None))
            if quote.id == quote_id
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="vendor quote not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize_quote(rec)
