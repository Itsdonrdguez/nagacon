from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.nsn_catalog.build import build_nsn_intelligence
from app.services.nsn_catalog.catalog_service import get_nsn_catalog_summary
from app.services.nsn_catalog.publog_decomp import import_publog_nsn
from app.services.nsn_catalog.publog_reference_service import (
    export_publog_reference_csv,
    export_publog_reference_json,
    search_publog_reference,
)
from app.services.nsn_catalog.publog_sync import get_publog_package_status, sync_publog_package
from app.services.nsn_catalog.provider_seeding import seed_providers_from_nsn_catalog
from app.services.nsn_catalog.refresh import refresh_nsn_intelligence
from app.services.search_jobs import start_search_job


router = APIRouter(prefix="/api/nsn", tags=["nsn-intelligence"])


@router.get("/publog/status")
def get_publog_status(
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return get_publog_package_status(db)


@router.post("/publog/sync")
def sync_publog(
    payload: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    payload = dict(payload or {})
    return sync_publog_package(
        db,
        zip_path=payload.get("zip_path"),
        publog_dir=payload.get("publog_dir"),
        source_version=payload.get("source_version"),
        nsns=payload.get("nsns"),
        target_limit=max(min(int(payload.get("target_limit") or 250), 1000), 1),
        dry_run=bool(payload.get("dry_run", False)),
        force=bool(payload.get("force", False)),
        compute_hash=bool(payload.get("compute_hash", False)),
    )


@router.post("/publog/sync-job")
def sync_publog_job(
    payload: dict | None = Body(default=None),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    payload = dict(payload or {})
    payload.setdefault("organization_id", getattr(current_org, "id", None))
    payload.setdefault("user_id", getattr(current_user, "id", None))
    payload["kind"] = "publog_sync"
    payload["target_limit"] = max(min(int(payload.get("target_limit") or 250), 1000), 1)
    return start_search_job("publog_sync", payload)


@router.get("/publog/reference/search")
def search_publog_reference_route(
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return search_publog_reference(
        db,
        dataset=dataset,
        mode=mode,
        q=q,
        nsn=nsn,
        part_number=part_number,
        cage=cage,
        fsc=fsc,
        limit=limit,
    )


@router.get("/publog/reference/export.csv")
def export_publog_reference_csv_route(
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return Response(
        content=export_publog_reference_csv(
            db,
            dataset=dataset,
            mode=mode,
            q=q,
            nsn=nsn,
            part_number=part_number,
            cage=cage,
            fsc=fsc,
            limit=limit,
        ),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="publog_{dataset}_{mode}.csv"'},
    )


@router.get("/publog/reference/export.json")
def export_publog_reference_json_route(
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return Response(
        content=export_publog_reference_json(
            db,
            dataset=dataset,
            mode=mode,
            q=q,
            nsn=nsn,
            part_number=part_number,
            cage=cage,
            fsc=fsc,
            limit=limit,
        ),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="publog_{dataset}_{mode}.json"'},
    )


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


@router.post("/{nsn}/build-job")
def build_nsn_job(
    nsn: str,
    run_usaspending: bool = True,
    seed_providers: bool = True,
    limit: int = 50,
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return start_search_job(
        "nsn_build",
        {
            "nsn": nsn,
            "run_usaspending": run_usaspending,
            "seed_providers": seed_providers,
            "limit": max(min(limit, 100), 1),
            "organization_id": getattr(current_org, "id", None),
            "user_id": getattr(current_user, "id", None),
        },
    )
