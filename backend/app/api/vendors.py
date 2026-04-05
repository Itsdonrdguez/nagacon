from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead
from app.schemas.vendor import VendorLeadOut, VendorLeadUpsertRequest, VendorQuoteOut, SeedRequest, UpsertRequest
from app.services.vendor_service import (
    list_quotes,
    seed_quotes_from_parsed,
    sync_vendor_leads_from_parsed,
    update_vendor_lead,
    upsert_quote,
)
from app.services.workspace_service import ensure_parsed


router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.get("/leads", response_model=list[VendorLeadOut])
def get_leads(
    opportunity_id: int,
    include_suppressed: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)

    if not include_suppressed:
        query = query.filter(VendorLead.status != "SUPPRESSED")

    return query.order_by(VendorLead.id.desc()).all()


@router.post("/leads/sync")
def sync_leads(req: SeedRequest, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    out = sync_vendor_leads_from_parsed(db, opp)
    out["cage_count"] = len(parsed.get("cage_codes") or [])
    out["text_source"] = parsed.get("text_source") or {}
    return out


@router.post("/leads/upsert", response_model=VendorLeadOut)
def upsert_lead(req: VendorLeadUpsertRequest, db: Session = Depends(get_db)):
    if req.lead_id is None:
        raise HTTPException(status_code=400, detail="lead_id required")
    patch = req.model_dump(exclude={"opportunity_id", "lead_id"}, exclude_none=False)
    try:
        rec = update_vendor_lead(db, req.opportunity_id, req.lead_id, patch)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return rec


@router.get("/quotes", response_model=list[VendorQuoteOut])
def get_quotes(opportunity_id: int, db: Session = Depends(get_db)):
    return list_quotes(db, opportunity_id)


@router.post("/quotes/seed")
def seed_quotes(req: SeedRequest, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    parsed = ensure_parsed(db, opp)
    out = seed_quotes_from_parsed(db, opp)
    out["text_source"] = parsed.get("text_source") or {}
    return out


@router.post("/quotes/upsert", response_model=VendorQuoteOut)
def upsert(req: UpsertRequest, db: Session = Depends(get_db)):
    patch = req.model_dump(exclude={"opportunity_id", "cage", "part_number"}, exclude_none=True)
    try:
        rec = upsert_quote(db, req.opportunity_id, req.cage, req.part_number, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return rec
