from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.notifications import build_notifications


router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return build_notifications(db, organization_id=getattr(current_org, "id", None), limit=limit)
