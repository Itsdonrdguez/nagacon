from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.data_exchange import (
    export_opportunities_csv,
    export_providers_csv,
    export_quotes_csv,
    export_work_queue_csv,
)
from app.services.export_service import build_bid_package_zip


router = APIRouter(prefix="/api/export", tags=["export"])


def _parse_code_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


@router.get("/bid_package")
def export_bid_package(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    try:
        filename, data = build_bid_package_zip(
            db,
            opportunity_id,
            organization_id=getattr(current_org, "id", None),
        )
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


@router.get("/opportunities.csv")
def export_opportunities(
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    agency: str | None = None,
    state: str | None = None,
    naics_codes: str | None = None,
    fsc_codes: str | None = None,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return Response(
        content=export_opportunities_csv(
            db,
            organization_id=getattr(current_org, "id", None),
            q=q,
            source=source,
            set_aside_type=set_aside_type,
            due_window=due_window,
            nsn=nsn,
            agency=agency,
            state=state,
            naics_codes=_parse_code_list(naics_codes),
            fsc_codes=_parse_code_list(fsc_codes),
        ),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="opportunities.csv"'},
    )
