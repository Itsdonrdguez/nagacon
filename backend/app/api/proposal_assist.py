from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.proposal_assist_service import generate_proposal_draft

router = APIRouter(prefix="/api/proposal-assist", tags=["proposal-assist"])


@router.post("/opportunities/{opportunity_id}/draft")
def proposal_draft(opportunity_id: int, db: Session = Depends(get_db)):
    try:
        return generate_proposal_draft(opportunity_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
