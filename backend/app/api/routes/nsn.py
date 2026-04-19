from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.services.nsn_catalog.build import build_nsn_intelligence
from app.services.nsn_catalog.catalog_service import get_nsn_catalog_summary
from app.services.nsn_catalog.publog_decomp import import_publog_nsn
from app.services.nsn_catalog.provider_seeding import seed_providers_from_nsn_catalog
from app.services.nsn_catalog.refresh import refresh_nsn_intelligence


router = APIRouter(prefix="/api/nsn", tags=["nsn-intelligence"])


@router.get("/{nsn}")
def get_nsn_intelligence(
    nsn: str,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = get_nsn_catalog_summary(db, nsn)
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["message"])
    return result


@router.post("/{nsn}/seed-providers")
def seed_nsn_catalog_providers(
    nsn: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = seed_providers_from_nsn_catalog(
        db,
        nsn,
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["errors"][0])
    return result


@router.post("/{nsn}/refresh")
def refresh_nsn(
    nsn: str,
    run_usaspending: bool = True,
    seed_providers: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = refresh_nsn_intelligence(
        db,
        nsn,
        run_usaspending=run_usaspending,
        seed_providers=seed_providers,
        limit=max(min(limit, 100), 1),
        organization_id=getattr(current_org, "id", None),
    )
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/{nsn}/import-publog")
def import_nsn_from_publog(
    nsn: str,
    dry_run: bool = False,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = import_publog_nsn(db, nsn, dry_run=dry_run)
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/{nsn}/build")
def build_nsn(
    nsn: str,
    run_usaspending: bool = True,
    seed_providers: bool = True,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    result = build_nsn_intelligence(
        db,
        nsn,
        run_usaspending=run_usaspending,
        seed_providers=seed_providers,
        limit=max(min(limit, 100), 1),
        organization_id=getattr(current_org, "id", None),
    )
    if result.get("status") == "invalid_nsn":
        raise HTTPException(status_code=422, detail=result["error"])
    return result
