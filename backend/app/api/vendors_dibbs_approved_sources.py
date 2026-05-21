from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_organization, get_current_user
from app.services.dibbs.approved_source_leads import seed_vendor_leads_from_dibbs_approved_sources

router = APIRouter(
    prefix="/api/vendors",
    tags=["vendors"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


@router.post("/dibbs/approved-sources/seed")
def seed_dibbs_approved_sources(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        return {"ok": False, "error": "opportunity_id is required"}

    return seed_vendor_leads_from_dibbs_approved_sources(
        db=db,
        opportunity_id=int(opportunity_id),
    )
