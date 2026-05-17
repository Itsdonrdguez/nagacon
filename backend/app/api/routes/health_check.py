from __future__ import annotations

from fastapi import APIRouter, Depends
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.opportunity import Opportunity
from app.services.app_settings_service import get_setting
from app.services.org_service import ensure_default_organization
from app.services.research.usaspending_research_service import search_usaspending_for_opportunity
from app.services.provider_settings_service import get_effective_sam_api_key, get_effective_sam_api_key_source
from app.research.predecessor_history import find_predecessor_opportunities
from app.services.search_jobs import DEFAULT_LANE, QUEUE_LANE, VENDOR_LANE
from app.services.storage import storage_root

router = APIRouter(prefix="/api/health", tags=["health"])


def _bool_label(value: bool) -> str:
    return "YES" if value else "NO"


def _path_status(value: str | None) -> dict[str, str | bool | None]:
    raw = str(value or "").strip()
    if not raw:
        return {"configured": False, "path": None, "exists": False}
    path = Path(raw)
    return {
        "configured": True,
        "path": str(path),
        "exists": path.exists(),
    }


@router.get("/")
def health_check(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    checks: dict[str, str] = {}
    opp_id = None

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "OK"
    except Exception as e:
        checks["database"] = f"ERROR: {e}"

    try:
        count = db.query(Opportunity).count()
        checks["opportunities_table"] = f"OK ({count} records)"
    except Exception as e:
        checks["opportunities_table"] = f"ERROR: {e}"

    try:
        opp = db.query(Opportunity).order_by(Opportunity.id.asc()).first()
        if opp:
            opp_id = int(opp.id)
            checks["sample_opportunity"] = f"OK (id={opp_id})"
        else:
            checks["sample_opportunity"] = "NO DATA"
    except Exception as e:
        checks["sample_opportunity"] = f"ERROR: {e}"

    sam_key_source = get_effective_sam_api_key_source(db, user_id=getattr(current_user, "id", None))
    checks["sam_api_key"] = (
        f"OK ({sam_key_source})"
        if bool(get_effective_sam_api_key(db, user_id=getattr(current_user, "id", None)) or getattr(settings, "SAM_API_KEY", None))
        else "MISSING"
    )

    if opp_id:
        try:
            preds = find_predecessor_opportunities(db, opp_id)
            checks["predecessor_engine"] = f"OK ({len(preds)} matches)"
        except Exception as e:
            checks["predecessor_engine"] = f"ERROR: {e}"

        try:
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            research = search_usaspending_for_opportunity(opp, db=db)
            checks["usaspending"] = f"OK ({research.get('awards_found', 0)} awards)"
        except Exception as e:
            checks["usaspending"] = f"ERROR: {e}"
    else:
        checks["predecessor_engine"] = "SKIPPED"
        checks["usaspending"] = "SKIPPED"

    org = ensure_default_organization(db)
    pdf_download_path = get_setting(db, "pdf_download_path", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_path = get_setting(db, "master_catalog_export_path", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_last_written_at = get_setting(db, "master_catalog_export_last_written_at", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_last_row_count = get_setting(db, "master_catalog_export_last_row_count", default="0", organization_id=getattr(org, "id", None)) or "0"
    storage_backend = str(getattr(settings, "STORAGE_BACKEND", "local") or "local").lower()
    runtime = {
        "app_env": str(getattr(settings, "APP_ENV", "dev") or "dev"),
        "app_role": str(getattr(settings, "APP_ROLE", "web") or "web"),
        "local_mode": bool(getattr(settings, "LOCAL_MODE", False)),
        "search_job_runner": str(getattr(settings, "SEARCH_JOB_RUNNER", "thread") or "thread"),
        "search_job_stale_seconds": int(getattr(settings, "SEARCH_JOB_STALE_SECONDS", 1800) or 1800),
        "sam_api_key_source": sam_key_source,
        "search_job_lane_concurrency": {
            QUEUE_LANE: int(getattr(settings, "SEARCH_JOB_QUEUE_MAX_CONCURRENCY", 2) or 2),
            VENDOR_LANE: int(getattr(settings, "SEARCH_JOB_VENDOR_MAX_CONCURRENCY", 2) or 2),
            DEFAULT_LANE: int(getattr(settings, "SEARCH_JOB_MAX_CONCURRENCY", 4) or 4),
        },
        "auto_ingest_enabled": bool(getattr(settings, "AUTO_INGEST_ENABLED", True)),
        "auto_file_prune_enabled": bool(getattr(settings, "AUTO_FILE_PRUNE_ENABLED", True)),
        "storage_backend": storage_backend,
        "storage_local_root": str(storage_root()) if storage_backend == "local" else None,
        "pdf_download_path": pdf_download_path or None,
        "master_catalog_export_path": master_catalog_export_path or None,
        "master_catalog_export_last_written_at": master_catalog_export_last_written_at or None,
        "master_catalog_export_last_row_count": int(master_catalog_export_last_row_count or 0),
        "publog_data_dir": _path_status(getattr(settings, "PUBLOG_DATA_DIR", "")),
        "publog_dvd_zip": _path_status(getattr(settings, "PUBLOG_DVD_ZIP", "")),
        "wbparts_enabled": bool(getattr(settings, "WBPARTS_ENABLED", True)),
        "wbparts_cache_days": int(getattr(settings, "WBPARTS_CACHE_DAYS", 14) or 14),
    }

    checks["local_mode"] = _bool_label(runtime["local_mode"])
    checks["storage_backend"] = str(runtime["storage_backend"]).upper()
    checks["storage_root"] = runtime["storage_local_root"] or "REMOTE"
    checks["pdf_download_path"] = runtime["pdf_download_path"] or "USING STORAGE ROOT"
    checks["master_catalog_export_path"] = runtime["master_catalog_export_path"] or "NOT CONFIGURED"
    checks["master_catalog_export_rows"] = str(runtime["master_catalog_export_last_row_count"])
    checks["master_catalog_export_last_written_at"] = runtime["master_catalog_export_last_written_at"] or "NEVER"
    checks["publog_data_dir"] = (
        f"OK ({runtime['publog_data_dir']['path']})"
        if runtime["publog_data_dir"]["configured"] and runtime["publog_data_dir"]["exists"]
        else ("MISSING" if runtime["publog_data_dir"]["configured"] else "NOT CONFIGURED")
    )
    checks["publog_dvd_zip"] = (
        f"OK ({runtime['publog_dvd_zip']['path']})"
        if runtime["publog_dvd_zip"]["configured"] and runtime["publog_dvd_zip"]["exists"]
        else ("MISSING" if runtime["publog_dvd_zip"]["configured"] else "NOT CONFIGURED")
    )

    return {"status": "running", "checks": checks, "runtime": runtime}
