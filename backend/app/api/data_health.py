from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.data_health import build_data_health


router = APIRouter(prefix="/api/data-health", tags=["data-health"])


@router.get("")
def get_data_health(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return build_data_health(db, organization_id=getattr(current_org, "id", None))
