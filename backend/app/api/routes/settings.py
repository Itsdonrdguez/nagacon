from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.services.app_settings_service import get_setting, upsert_setting
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
    keys = _split_keys(raw)
    return {
        "organization": _org_payload(org),
        "external_api_keys": _masked_keys(keys),
        "external_api_keys_csv": "",
        "external_api_key_count": len(keys),
        "external_api_keys_display": ", ".join(_masked_keys(keys)),
        "configured": len(keys) > 0,
    }


@router.put("/integrations")
def update_integration_settings(payload: dict, db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    org_id = getattr(org, "id", None)
    existing_value = get_setting(db, "external_api_keys", default="", organization_id=org_id) or ""
    csv_value = (payload.get("external_api_keys_csv") or "").strip()
    clear_requested = bool(payload.get("clear_external_api_keys"))
    if not csv_value and existing_value and not clear_requested:
        csv_value = existing_value
    if clear_requested:
        csv_value = ""
    record = upsert_setting(db, "external_api_keys", csv_value, organization_id=getattr(org, "id", None))
    keys = _split_keys(csv_value)
    return {
        "status": "saved",
        "record_id": getattr(record, "id", None),
        "organization": _org_payload(org),
        "external_api_keys": _masked_keys(keys),
        "external_api_keys_csv": "",
        "external_api_key_count": len(keys),
        "external_api_keys_display": ", ".join(_masked_keys(keys)),
        "configured": len(keys) > 0,
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
