from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.vendors.discovery import discover_vendors_for_opportunity

router = APIRouter(
    prefix="/api/vendor-discovery",
    tags=["vendor-discovery"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


@router.post("/opportunities/{opportunity_id}")
def discover_for_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    try:
        return discover_vendors_for_opportunity(opportunity_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
