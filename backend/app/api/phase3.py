from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead
from app.schemas.quote import QuoteCreate, QuoteOut
from app.services.quotes.calculations import create_quote_with_calc

router = APIRouter(prefix="/api/phase3", tags=["phase3"])


@router.post("/opportunities/{opportunity_id}/suggested-quote", response_model=QuoteOut)
def create_suggested_quote(
    opportunity_id: int,
    vendor_lead_id: int | None = None,
    markup_pct: float = 12.0,
    unit_cost: float = 0.0,
    db: Session = Depends(get_db),
):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if vendor_lead_id is None:
        lead = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id).order_by(VendorLead.id.asc()).first()
    else:
        lead = db.query(VendorLead).filter(
            VendorLead.id == vendor_lead_id,
            VendorLead.opportunity_id == opportunity_id,
        ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Vendor lead not found")

    raw_payload = getattr(opp, "raw_payload", None) or {}
    selected_sol = raw_payload.get("dibbs_selected_solicitation") or {}
    qty_raw = selected_sol.get("qty") or 1
    try:
        quantity = float(qty_raw)
    except Exception:
        quantity = 1.0

    item = QuoteCreate(
        opportunity_id=opportunity_id,
        vendor_id=lead.id,
        line_item=(getattr(opp, "title", None) or "Quoted Item"),
        quantity=quantity,
        unit_cost=float(unit_cost or 0),
        markup_pct=float(markup_pct or 0),
        assumptions=f"Suggested from vendor lead {lead.company_name or lead.cage or lead.id}",
    )
    return create_quote_with_calc(item, db)
