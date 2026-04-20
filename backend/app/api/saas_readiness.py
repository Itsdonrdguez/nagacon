from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.saas_readiness import build_org_scope_audit


router = APIRouter(prefix="/api/saas-readiness", tags=["saas-readiness"])


@router.get("/org-scope")
def get_org_scope_audit(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return build_org_scope_audit(db, organization_id=getattr(current_org, "id", None))
