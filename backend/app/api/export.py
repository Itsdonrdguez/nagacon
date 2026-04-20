from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.data_exchange import export_providers_csv, export_quotes_csv, export_work_queue_csv
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


@router.get("/providers.csv")
def export_providers(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return Response(
        content=export_providers_csv(db, organization_id=getattr(current_org, "id", None)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="providers.csv"'},
    )


@router.get("/vendor_quotes.csv")
def export_vendor_quotes(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return Response(
        content=export_quotes_csv(db, opportunity_id, organization_id=getattr(current_org, "id", None)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vendor_quotes_{opportunity_id}.csv"'},
    )


@router.get("/work_queue.csv")
def export_work_queue(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return Response(
        content=export_work_queue_csv(db, organization_id=getattr(current_org, "id", None)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="work_queue.csv"'},
    )
