from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import requests

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.services.research.usaspending_research_service import (
    search_usaspending_for_opportunity,
    seed_usaspending_vendors_into_leads,
)

router = APIRouter(prefix="/api/research/usaspending", tags=["research"])


@router.post("/opportunities/{opportunity_id}")
def research_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    try:
        return search_usaspending_for_opportunity(opp, db=db)
    except requests.RequestException as exc:
        return {"opportunity_id": opportunity_id, "results": [], "error": str(exc), "source": "usaspending"}


@router.post("/opportunities/{opportunity_id}/seed-leads")
def seed_leads(
    opportunity_id: int,
    seed_mode: str = Query("product_only", pattern="^(all|product_only|strict)$"),
    db: Session = Depends(get_db),
):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    try:
        research = search_usaspending_for_opportunity(opp, db=db)
    except requests.RequestException as exc:
        return {"opportunity_id": opportunity_id, "seeded": 0, "error": str(exc), "source": "usaspending"}
    return seed_usaspending_vendors_into_leads(
        db=db,
        opp=opp,
        research_result=research,
        seed_mode=seed_mode,
    )
