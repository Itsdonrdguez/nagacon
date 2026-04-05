from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.repositories.opportunities import OpportunityRepository
from app.schemas.opportunity import IngestResult, OpportunityCreate, OpportunityRead, OpportunityUpdate, RawOpportunity
from app.services.opportunities.ingest import ingest_raw_opportunities

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    return OpportunityRepository(db).list(limit=limit, offset=offset)


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    opp = OpportunityRepository(db).get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


@router.post("", response_model=OpportunityRead)
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db)):
    return OpportunityRepository(db).create(payload)


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(opportunity_id: int, payload: OpportunityUpdate, db: Session = Depends(get_db)):
    updated = OpportunityRepository(db).update(opportunity_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return updated


@router.post("/ingest", response_model=IngestResult)
def ingest_opportunities(raw_records: list[RawOpportunity], db: Session = Depends(get_db)):
    return ingest_raw_opportunities(db, raw_records)
