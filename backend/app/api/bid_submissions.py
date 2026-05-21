from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.opportunity import Opportunity
from app.schemas.bid_submission import BidSubmissionOut, BidSubmissionUpsert
from app.services.bid_submission_service import get_submission, upsert_submission


router = APIRouter(
    prefix="/api/submissions",
    tags=["submissions"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


def _scoped_opportunity(db: Session, opportunity_id: int, organization_id: int | None) -> Opportunity:
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if organization_id is not None:
        query = query.filter(or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)))
    opp = query.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if organization_id is not None and getattr(opp, "organization_id", None) is None:
        opp.organization_id = organization_id
        db.add(opp)
        db.commit()
        db.refresh(opp)
    return opp


@router.get("", response_model=BidSubmissionOut | None)
def get(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    _scoped_opportunity(db, opportunity_id, getattr(current_org, "id", None))
    return get_submission(db, opportunity_id)


@router.post("/upsert", response_model=BidSubmissionOut)
def upsert(req: BidSubmissionUpsert, db: Session = Depends(get_db), current_org=Depends(get_current_organization), current_user=Depends(get_current_user)):
    opp = _scoped_opportunity(db, req.opportunity_id, getattr(current_org, "id", None))
    patch = req.model_dump(exclude={"opportunity_id"}, exclude_none=True)
    try:
        return upsert_submission(
            db,
            req.opportunity_id,
            patch,
            organization_id=getattr(current_org, "id", None),
            user_id=getattr(current_user, "id", None),
            opportunity=opp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
