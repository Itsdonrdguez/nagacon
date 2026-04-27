from __future__ import annotations

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_organization, get_db
from app.services.auth_service import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_DAYS,
    authenticate_user,
    clear_user_session,
    create_user_account,
    get_user_by_session_token,
    start_user_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_payload(user, current_org):
    return {
        "authenticated": bool(user),
        "user": {
            "id": getattr(user, "id", None),
            "email": getattr(user, "email", None),
            "full_name": getattr(user, "full_name", None),
            "role": getattr(user, "role", None),
            "is_active": getattr(user, "is_active", True),
        } if user else None,
        "organization": {
            "id": getattr(current_org, "id", None),
            "name": getattr(current_org, "name", None),
            "slug": getattr(current_org, "slug", None),
            "is_default": getattr(current_org, "is_default", True),
        } if user and current_org else None,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    app_env = str(getattr(settings, "APP_ENV", "dev")).lower()
    is_secure = bool(getattr(settings, "SESSION_COOKIE_SECURE", False)) or app_env in {"prod", "production"}
    same_site = str(getattr(settings, "SESSION_COOKIE_SAMESITE", "lax") or "lax").lower()
    cookie_domain = str(getattr(settings, "SESSION_COOKIE_DOMAIN", "") or "").strip() or None
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite=same_site,
        secure=is_secure,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        path="/",
        domain=cookie_domain,
    )


def _clear_session_cookie(response: Response) -> None:
    same_site = str(getattr(settings, "SESSION_COOKIE_SAMESITE", "lax") or "lax").lower()
    cookie_domain = str(getattr(settings, "SESSION_COOKIE_DOMAIN", "") or "").strip() or None
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite=same_site, domain=cookie_domain)


@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    current_user = get_user_by_session_token(db, x_session_token or session_token)
    return _auth_payload(current_user, current_org if current_user else None)


@router.post("/signup")
def signup(
    response: Response,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    full_name = str(payload.get("full_name") or "").strip() or None
    if not email:
        raise HTTPException(status_code=422, detail="Email is required")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    try:
        user = create_user_account(db, email=email, password=password, full_name=full_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token, _ = start_user_session(db, user)
    _set_session_cookie(response, token)
    payload = _auth_payload(user, current_org)
    payload["session_token"] = token
    return payload


@router.post("/login")
def login(
    response: Response,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    identifier = str(payload.get("identifier") or payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    user = authenticate_user(db, identifier=identifier, password=password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username/email or password")
    token, _ = start_user_session(db, user)
    _set_session_cookie(response, token)
    payload = _auth_payload(user, current_org)
    payload["session_token"] = token
    return payload


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    current_user = get_user_by_session_token(db, x_session_token or session_token)
    if current_user:
        clear_user_session(db, current_user)
    _clear_session_cookie(response)
    return {"status": "logged_out"}
