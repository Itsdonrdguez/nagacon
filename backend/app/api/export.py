from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.export_service import build_bid_package_zip


router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/bid_package")
def export_bid_package(opportunity_id: int, db: Session = Depends(get_db)):
    try:
        filename, data = build_bid_package_zip(db, opportunity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
