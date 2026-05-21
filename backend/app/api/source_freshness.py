from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.source_freshness import build_source_freshness


router = APIRouter(prefix="/api/source-freshness", tags=["source-freshness"])


@router.get("")
def get_source_freshness(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return build_source_freshness(db, organization_id=getattr(current_org, "id", None))
