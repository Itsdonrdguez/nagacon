from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.app_settings_service import get_setting, upsert_setting
from app.services.org_service import ensure_default_organization
from app.services.provider_settings_service import get_provider_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/integrations")
def get_integration_settings(db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    raw = get_setting(db, "external_api_keys", default="", organization_id=getattr(org, "id", None)) or ""
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    return {
        "organization": {
            "id": getattr(org, "id", None),
            "name": getattr(org, "name", None),
            "slug": getattr(org, "slug", None),
        } if org else None,
        "external_api_keys": keys,
        "external_api_keys_csv": ", ".join(keys),
        "configured": len(keys) > 0,
    }


@router.put("/integrations")
def update_integration_settings(payload: dict, db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    csv_value = (payload.get("external_api_keys_csv") or "").strip()
    record = upsert_setting(db, "external_api_keys", csv_value, organization_id=getattr(org, "id", None))
    keys = [item.strip() for item in csv_value.split(",") if item.strip()]
    return {
        "status": "saved",
        "record_id": getattr(record, "id", None),
        "organization": {
            "id": getattr(org, "id", None),
            "name": getattr(org, "name", None),
            "slug": getattr(org, "slug", None),
        } if org else None,
        "external_api_keys": keys,
        "external_api_keys_csv": ", ".join(keys),
        "configured": len(keys) > 0,
    }


@router.get("/providers")
def get_provider_settings_route(db: Session = Depends(get_db)):
    return get_provider_settings(db)


@router.put("/providers")
def update_provider_settings(payload: dict, db: Session = Depends(get_db)):
    org = ensure_default_organization(db)
    org_id = getattr(org, "id", None)

    def save(key: str, value: str | None):
        upsert_setting(db, key, (value or "").strip(), organization_id=org_id)

    save("sam_api_key", payload.get("sam_api_key"))
    save("openai_api_key", payload.get("openai_api_key"))
    save("openai_model", payload.get("openai_model"))
    save("smtp_host", payload.get("smtp_host"))
    save("smtp_port", payload.get("smtp_port"))
    save("smtp_from_email", payload.get("smtp_from_email"))

    result = get_provider_settings(db)
    result["status"] = "saved"
    return result
