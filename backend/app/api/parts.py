from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.ingest_enrichment import enrich_dibbs_opportunities_after_ingest
from app.services.part_finder import find_part_for_nsn, find_part_for_opportunity, find_parts_batch

router = APIRouter(prefix="/api/parts", tags=["part-finder"])


@router.get("/opportunity/{opportunity_id}")
def get_part_for_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = find_part_for_opportunity(db, opportunity_id, organization_id=getattr(current_org, "id", None))
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/opportunity/{opportunity_id}/refresh")
def refresh_part_for_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = enrich_dibbs_opportunities_after_ingest(
        db,
        [opportunity_id],
        organization_id=getattr(current_org, "id", None),
        max_items=1,
        queue_nsn_build=False,
    )
    if result.get("errors") and not result.get("items"):
        raise HTTPException(status_code=400, detail=result["errors"][0].get("error") or "Part Finder refresh failed")
    return result


@router.get("/nsn/{nsn}")
def get_part_for_nsn(
    nsn: str,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = find_part_for_nsn(db, nsn, organization_id=getattr(current_org, "id", None))
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/find")
def find_parts(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    opportunity_ids = payload.get("opportunity_ids") or []
    nsns = payload.get("nsns") or []
    limit = max(min(int(payload.get("limit") or 25), 50), 1)
    return find_parts_batch(
        db,
        opportunity_ids=[int(item) for item in opportunity_ids][:limit],
        nsns=[str(item) for item in nsns][:limit],
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )
