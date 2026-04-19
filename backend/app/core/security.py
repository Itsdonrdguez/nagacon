from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from app.core.config import settings
from app.core.deps import get_db
from app.services.app_settings_service import get_setting
from app.services.org_service import ensure_default_organization


integration_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_integration_keys(db=None) -> list[str]:
    raw = getattr(settings, "EXTERNAL_API_KEYS", "") or ""
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    if db is not None:
        org = ensure_default_organization(db)
        stored = get_setting(db, "external_api_keys", default="", organization_id=getattr(org, "id", None)) or ""
        values.extend([item.strip() for item in str(stored).split(",") if item.strip()])
    deduped: list[str] = []
    seen = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def require_integration_api_key(
    api_key: str | None = Depends(integration_api_key_header),
    db=Depends(get_db),
) -> str:
    allowed_keys = _configured_integration_keys(db=db)
    if not allowed_keys:
        raise HTTPException(status_code=503, detail="External API access is not configured")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if not any(secrets.compare_digest(api_key, allowed) for allowed in allowed_keys):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key
