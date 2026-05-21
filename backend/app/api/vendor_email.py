from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.vendor_email_automation import generate_quote_request_email

router = APIRouter(
    prefix="/api/vendor-email",
    tags=["vendor-email"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


@router.post("/opportunities/{opportunity_id}/draft")
def email_draft(
    opportunity_id: int,
    vendor_quote_id: int | None = Query(default=None),
    vendor_lead_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return generate_quote_request_email(
            opportunity_id=opportunity_id,
            vendor_quote_id=vendor_quote_id,
            vendor_lead_id=vendor_lead_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
