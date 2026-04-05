from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.schemas.bid_submission import BidSubmissionOut, BidSubmissionUpsert
from app.services.bid_submission_service import get_submission, upsert_submission


router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.get("", response_model=BidSubmissionOut | None)
def get(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return get_submission(db, opportunity_id)


@router.post("/upsert", response_model=BidSubmissionOut)
def upsert(req: BidSubmissionUpsert, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter(Opportunity.id == req.opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    patch = req.model_dump(exclude={"opportunity_id"}, exclude_none=True)
    return upsert_submission(db, req.opportunity_id, patch)
