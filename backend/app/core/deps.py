from types import SimpleNamespace

from fastapi import Cookie, Depends, Header

from app.core.db import SessionLocal
from app.services.auth_service import SESSION_COOKIE_NAME, get_or_create_user_by_email, get_user_by_session_token
from app.services.org_service import ensure_default_organization

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db=Depends(get_db),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    session_user = get_user_by_session_token(db, session_token)
    if session_user:
        return session_user
    user = get_or_create_user_by_email(db, x_user_email)
    if user:
        return user
    fallback_email = (x_user_email or "owner@nagacon.local").strip().lower() or "owner@nagacon.local"
    fallback_name = fallback_email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return SimpleNamespace(
        id=None,
        email=fallback_email,
        full_name=fallback_name or "Default Owner",
        role="OWNER",
        organization_id=None,
        is_active=True,
    )


def get_current_organization(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = ensure_default_organization(db)
    if current_user is not None and getattr(current_user, "organization_id", None) and org is not None:
        if current_user.organization_id == org.id:
            return org
    if current_user is not None and getattr(current_user, "organization_id", None) and org is None:
        return None
    if org:
        return org
    return SimpleNamespace(
        id=None,
        name="Default Organization",
        slug="default",
        is_default=True,
    )
