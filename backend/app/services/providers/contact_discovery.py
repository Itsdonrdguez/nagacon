from __future__ import annotations

import re
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.provider import Provider

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})")


def _clean(value: Any, max_len: int | None = None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _fetch_page(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 NagaCon Provider Contact Discovery"}
    response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text" not in content_type and "html" not in content_type:
        return ""
    return response.text[:250000]


def _extract_contacts(html: str) -> dict[str, str | None]:
    emails = [email for email in EMAIL_RE.findall(html or "") if not email.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    phones = PHONE_RE.findall(html or "")
    return {
        "email": _clean(emails[0], 240) if emails else None,
        "phone": _clean(phones[0], 80) if phones else None,
    }


def discover_provider_contacts(
    db: Session,
    *,
    organization_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    query = db.query(Provider).filter(Provider.website.is_not(None))
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    providers = query.order_by(Provider.updated_at.desc(), Provider.id.desc()).limit(max(min(limit, 500), 1)).all()

    checked = 0
    updated = 0
    errors: list[str] = []
    for provider in providers:
        if provider.email and provider.phone:
            continue
        checked += 1
        try:
            html = _fetch_page(provider.website)
            contacts = _extract_contacts(html)
        except Exception as exc:
            errors.append(f"{provider.company_name}: {exc}")
            continue
        touched = False
        if contacts.get("email") and not provider.email:
            provider.email = contacts["email"]
            touched = True
        if contacts.get("phone") and not provider.phone:
            provider.phone = contacts["phone"]
            touched = True
        if touched:
            db.add(provider)
            updated += 1
    if updated:
        db.commit()
    return {"checked": checked, "updated": updated, "errors": errors[:10]}
