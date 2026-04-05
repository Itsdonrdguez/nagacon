from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.vendors.lead_cleanup import suppress_non_dibbs_leads_for_opportunity

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.post("/opportunities/{opportunity_id}/suppress-non-dibbs")
def suppress_non_dibbs(opportunity_id: int, db: Session = Depends(get_db)):
    return suppress_non_dibbs_leads_for_opportunity(db=db, opportunity_id=opportunity_id)
