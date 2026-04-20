from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.work_queue import build_daily_work_queue


router = APIRouter(prefix="/api/work-queue", tags=["work-queue"])


@router.get("/today")
def get_daily_work_queue(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return build_daily_work_queue(
        db,
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )
