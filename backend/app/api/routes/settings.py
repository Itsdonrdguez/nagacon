from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.services.app_settings_service import get_setting, upsert_setting
from app.services.master_catalog_export import write_master_catalog_export
from app.services.org_service import ensure_default_organization
from app.services.provider_settings_service import get_provider_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
SECRET_MASK = "********"


def _org_payload(org):
    return {
        "id": getattr(org, "id", None),
        "name": getattr(org, "name", None),
        "slug": getattr(org, "slug", None),
    } if org else None


def _split_keys(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _masked_keys(keys: list[str]) -> list[str]:
    return [SECRET_MASK for _ in keys]


@router.get("/integrations")
def get_integration_settings(db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    raw = get_setting(db, "external_api_keys", default="", organization_id=getattr(org, "id", None)) or ""
    pdf_download_path = get_setting(db, "pdf_download_path", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_path = get_setting(db, "master_catalog_export_path", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_last_written_at = get_setting(db, "master_catalog_export_last_written_at", default="", organization_id=getattr(org, "id", None)) or ""
    master_catalog_export_last_row_count = get_setting(db, "master_catalog_export_last_row_count", default="0", organization_id=getattr(org, "id", None)) or "0"
    keys = _split_keys(raw)
    return {
        "organization": _org_payload(org),
        "external_api_keys": _masked_keys(keys),
        "external_api_keys_csv": "",
        "external_api_key_count": len(keys),
        "external_api_keys_display": ", ".join(_masked_keys(keys)),
        "configured": len(keys) > 0,
        "pdf_download_path": pdf_download_path,
        "master_catalog_export_path": master_catalog_export_path,
        "master_catalog_export_last_written_at": master_catalog_export_last_written_at,
        "master_catalog_export_last_row_count": int(master_catalog_export_last_row_count or 0),
    }


@router.put("/integrations")
def update_integration_settings(payload: dict, db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    org_id = getattr(org, "id", None)
    existing_value = get_setting(db, "external_api_keys", default="", organization_id=org_id) or ""
    existing_pdf_download_path = get_setting(db, "pdf_download_path", default="", organization_id=org_id) or ""
    existing_master_catalog_export_path = get_setting(db, "master_catalog_export_path", default="", organization_id=org_id) or ""
    csv_value = (payload.get("external_api_keys_csv") or "").strip()
    pdf_download_path = (payload.get("pdf_download_path") or "").strip()
    master_catalog_export_path = (payload.get("master_catalog_export_path") or "").strip()
    clear_requested = bool(payload.get("clear_external_api_keys"))
    clear_pdf_path = bool(payload.get("clear_pdf_download_path"))
    clear_master_catalog_export_path = bool(payload.get("clear_master_catalog_export_path"))
    if not csv_value and existing_value and not clear_requested:
        csv_value = existing_value
    if not pdf_download_path and existing_pdf_download_path and not clear_pdf_path:
        pdf_download_path = existing_pdf_download_path
    if not master_catalog_export_path and existing_master_catalog_export_path and not clear_master_catalog_export_path:
        master_catalog_export_path = existing_master_catalog_export_path
    if clear_requested:
        csv_value = ""
    if clear_pdf_path:
        pdf_download_path = ""
    if clear_master_catalog_export_path:
        master_catalog_export_path = ""
    record = upsert_setting(db, "external_api_keys", csv_value, organization_id=getattr(org, "id", None))
    upsert_setting(db, "pdf_download_path", pdf_download_path, organization_id=getattr(org, "id", None))
    upsert_setting(db, "master_catalog_export_path", master_catalog_export_path, organization_id=getattr(org, "id", None))
    keys = _split_keys(csv_value)
    export_status = (
        write_master_catalog_export(db, organization_id=org_id)
        if master_catalog_export_path
        else {"written": False, "reason": "path_not_configured", "path": None, "row_count": 0}
    )
    return {
        "status": "saved",
        "record_id": getattr(record, "id", None),
        "organization": _org_payload(org),
        "external_api_keys": _masked_keys(keys),
        "external_api_keys_csv": "",
        "external_api_key_count": len(keys),
        "external_api_keys_display": ", ".join(_masked_keys(keys)),
        "configured": len(keys) > 0,
        "pdf_download_path": pdf_download_path,
        "master_catalog_export_path": master_catalog_export_path,
        "master_catalog_export_last_written_at": get_setting(db, "master_catalog_export_last_written_at", default="", organization_id=org_id) or "",
        "master_catalog_export_last_row_count": int(get_setting(db, "master_catalog_export_last_row_count", default="0", organization_id=org_id) or 0),
        "master_catalog_export_status": export_status,
    }


@router.get("/providers")
def get_provider_settings_route(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return get_provider_settings(db, user_id=getattr(current_user, "id", None))


@router.put("/providers")
def update_provider_settings(payload: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    org = ensure_default_organization(db)
    org_id = getattr(org, "id", None)
    user_id = getattr(current_user, "id", None)

    def save(key: str, value: str | None, *, preserve_blank: bool = False, clear_key: str | None = None):
        incoming = (value or "").strip()
        if preserve_blank and not incoming and not payload.get(clear_key or ""):
            return
        upsert_setting(db, key, "" if payload.get(clear_key or "") else incoming, organization_id=org_id, user_id=user_id)

    save("sam_api_key", payload.get("sam_api_key"), preserve_blank=True, clear_key="clear_sam_api_key")
    save("openai_api_key", payload.get("openai_api_key"), preserve_blank=True, clear_key="clear_openai_api_key")
    save("openai_model", payload.get("openai_model"))
    save("smtp_host", payload.get("smtp_host"))
    save("smtp_port", payload.get("smtp_port"))
    save("smtp_from_email", payload.get("smtp_from_email"))

    result = get_provider_settings(db, user_id=user_id)
    result["status"] = "saved"
    return result
