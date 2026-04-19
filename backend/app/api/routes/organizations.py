from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.org_service import ensure_default_organization

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("/current")
def get_current_organization(db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    return {
        "id": getattr(org, "id", None),
        "name": getattr(org, "name", None),
        "slug": getattr(org, "slug", None),
        "is_default": getattr(org, "is_default", True),
    }
