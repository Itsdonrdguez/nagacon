from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
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

    rows: list[dict] = []
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
        rows.append(row)
    return rows


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
def sync_leads(req: SeedRequest, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id)
    if org_id is not None:
        opp = opp.filter(Opportunity.organization_id == org_id)
    opp = opp.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    out = sync_vendor_leads_from_parsed(db, opp)
    provider_sync = seed_vendor_leads_from_providers(db, opp, parsed=parsed, organization_id=org_id)
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
    return [_serialize_quote(quote) for quote in list_quotes(db, opportunity_id, organization_id=getattr(current_org, "id", None))]


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
def seed_quotes(req: SeedRequest, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id)
    if org_id is not None:
        opp = opp.filter(Opportunity.organization_id == org_id)
    opp = opp.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    provider_sync = seed_vendor_leads_from_providers(db, opp, parsed=parsed, organization_id=org_id)
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
