from __future__ import annotations

from app.core.config import settings
from app.services.app_settings_service import get_setting
from app.services.org_service import ensure_default_organization


def _org_id(db):
    org = ensure_default_organization(db)
    return getattr(org, "id", None)


def get_provider_settings(db) -> dict:
    org_id = _org_id(db)
    sam_api_key = get_setting(db, "sam_api_key", default="", organization_id=org_id) or ""
    openai_api_key = get_setting(db, "openai_api_key", default="", organization_id=org_id) or ""
    openai_model = get_setting(db, "openai_model", default="gpt-4o-mini", organization_id=org_id) or "gpt-4o-mini"
    smtp_host = get_setting(db, "smtp_host", default="", organization_id=org_id) or ""
    smtp_port = get_setting(db, "smtp_port", default="", organization_id=org_id) or ""
    smtp_from_email = get_setting(db, "smtp_from_email", default="", organization_id=org_id) or ""

    return {
        "organization": {
            "id": org_id,
            "name": getattr(ensure_default_organization(db), "name", None),
            "slug": getattr(ensure_default_organization(db), "slug", None),
        } if ensure_default_organization(db) else None,
        "sam_api_key": sam_api_key,
        "openai_api_key": openai_api_key,
        "openai_model": openai_model,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_from_email": smtp_from_email,
        "sam_configured": bool(sam_api_key or getattr(settings, "SAM_API_KEY", None)),
        "openai_configured": bool(openai_api_key or getattr(settings, "OPENAI_API_KEY", None)),
        "smtp_configured": bool((smtp_host or getattr(settings, "SMTP_HOST", None)) and (smtp_from_email or getattr(settings, "SMTP_FROM_EMAIL", None))),
    }


def get_effective_sam_api_key(db) -> str | None:
    org_id = _org_id(db)
    return get_setting(db, "sam_api_key", default=getattr(settings, "SAM_API_KEY", None), organization_id=org_id)


def get_effective_openai_api_key(db) -> str | None:
    org_id = _org_id(db)
    return get_setting(db, "openai_api_key", default=getattr(settings, "OPENAI_API_KEY", None), organization_id=org_id)


def get_effective_openai_model(db) -> str:
    org_id = _org_id(db)
    return get_setting(db, "openai_model", default=getattr(settings, "OPENAI_PROPOSAL_MODEL", "gpt-4o-mini"), organization_id=org_id) or "gpt-4o-mini"


def get_effective_smtp_host(db) -> str | None:
    org_id = _org_id(db)
    return get_setting(db, "smtp_host", default=getattr(settings, "SMTP_HOST", None), organization_id=org_id)


def get_effective_smtp_port(db) -> str | None:
    org_id = _org_id(db)
    return get_setting(db, "smtp_port", default=str(getattr(settings, "SMTP_PORT", "")), organization_id=org_id)


def get_effective_smtp_from_email(db) -> str | None:
    org_id = _org_id(db)
    return get_setting(db, "smtp_from_email", default=getattr(settings, "SMTP_FROM_EMAIL", None), organization_id=org_id)
