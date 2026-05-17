from __future__ import annotations

from app.core.config import settings
from app.services.app_settings_service import get_setting
from app.services.org_service import ensure_default_organization

SECRET_MASK = "********"


def _org_id(db):
    org = ensure_default_organization(db)
    return getattr(org, "id", None)


def get_provider_settings(db, *, user_id: int | None = None) -> dict:
    org_id = _org_id(db)
    sam_api_key = get_setting(db, "sam_api_key", default="", organization_id=org_id, user_id=user_id) or ""
    org_sam_api_key = get_setting(db, "sam_api_key", default="", organization_id=org_id) or ""
    openai_api_key = get_setting(db, "openai_api_key", default="", organization_id=org_id, user_id=user_id) or ""
    openai_model = get_setting(db, "openai_model", default="gpt-4o-mini", organization_id=org_id, user_id=user_id) or "gpt-4o-mini"
    smtp_host = get_setting(db, "smtp_host", default="", organization_id=org_id, user_id=user_id) or ""
    smtp_port = get_setting(db, "smtp_port", default="", organization_id=org_id, user_id=user_id) or ""
    smtp_from_email = get_setting(db, "smtp_from_email", default="", organization_id=org_id, user_id=user_id) or ""

    return {
        "organization": {
            "id": org_id,
            "name": getattr(ensure_default_organization(db), "name", None),
            "slug": getattr(ensure_default_organization(db), "slug", None),
        } if ensure_default_organization(db) else None,
        "scope": "user" if user_id is not None else "organization",
        "user_id": user_id,
        "sam_api_key": "",
        "openai_api_key": "",
        "openai_model": openai_model,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_from_email": smtp_from_email,
        "sam_configured": bool(sam_api_key or getattr(settings, "SAM_API_KEY", None)),
        "sam_api_key_source": get_effective_sam_api_key_source(db, user_id=user_id),
        "sam_fallback_configured": bool(org_sam_api_key or getattr(settings, "SAM_API_KEY", None)),
        "openai_configured": bool(openai_api_key or getattr(settings, "OPENAI_API_KEY", None)),
        "sam_api_key_display": SECRET_MASK if bool(sam_api_key or getattr(settings, "SAM_API_KEY", None)) else "",
        "openai_api_key_display": SECRET_MASK if bool(openai_api_key or getattr(settings, "OPENAI_API_KEY", None)) else "",
        "smtp_configured": bool((smtp_host or getattr(settings, "SMTP_HOST", None)) and (smtp_from_email or getattr(settings, "SMTP_FROM_EMAIL", None))),
    }


def get_effective_sam_api_key(db, *, user_id: int | None = None) -> str | None:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "sam_api_key", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "sam_api_key", default=getattr(settings, "SAM_API_KEY", None), organization_id=org_id)


def get_effective_sam_api_key_source(db, *, user_id: int | None = None) -> str:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "sam_api_key", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return "user"
    org_value = get_setting(db, "sam_api_key", default=None, organization_id=org_id)
    if org_value:
        return "organization"
    return "environment" if getattr(settings, "SAM_API_KEY", None) else "missing"


def get_sam_api_key_candidates(db, *, user_id: int | None = None) -> list[tuple[str, str]]:
    org_id = _org_id(db)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(source: str, value: str | None) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append((source, text))

    if user_id is not None:
        add("user", get_setting(db, "sam_api_key", default=None, organization_id=org_id, user_id=user_id))
    add("organization", get_setting(db, "sam_api_key", default=None, organization_id=org_id))
    add("environment", getattr(settings, "SAM_API_KEY", None))
    return candidates


def get_effective_openai_api_key(db, *, user_id: int | None = None) -> str | None:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "openai_api_key", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "openai_api_key", default=getattr(settings, "OPENAI_API_KEY", None), organization_id=org_id)


def get_effective_openai_model(db, *, user_id: int | None = None) -> str:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "openai_model", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "openai_model", default=getattr(settings, "OPENAI_PROPOSAL_MODEL", "gpt-4o-mini"), organization_id=org_id) or "gpt-4o-mini"


def get_effective_smtp_host(db, *, user_id: int | None = None) -> str | None:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "smtp_host", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "smtp_host", default=getattr(settings, "SMTP_HOST", None), organization_id=org_id)


def get_effective_smtp_port(db, *, user_id: int | None = None) -> str | None:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "smtp_port", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "smtp_port", default=str(getattr(settings, "SMTP_PORT", "")), organization_id=org_id)


def get_effective_smtp_from_email(db, *, user_id: int | None = None) -> str | None:
    org_id = _org_id(db)
    if user_id is not None:
        user_value = get_setting(db, "smtp_from_email", default=None, organization_id=org_id, user_id=user_id)
        if user_value:
            return user_value
    return get_setting(db, "smtp_from_email", default=getattr(settings, "SMTP_FROM_EMAIL", None), organization_id=org_id)
