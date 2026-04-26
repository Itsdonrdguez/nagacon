from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.organization import User
from app.services.org_service import ensure_default_organization


DEFAULT_USER_EMAIL = "admin@nagacon.local"
DEFAULT_USER_NAME = "Admin"
DEFAULT_USER_ROLE = "OWNER"
DEFAULT_USER_USERNAME = "admin"
DEFAULT_USER_PASSWORD = "admin"
SESSION_COOKIE_NAME = "nagacon_session"
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 240000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def _normalize_identifier(identifier: str | None) -> str:
    return str(identifier or "").strip().lower()


def _password_hash(password: str, *, salt: str | None = None) -> str:
    chosen_salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        chosen_salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${chosen_salt}${derived.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations_raw),
        ).hex()
        return hmac.compare_digest(derived, digest)
    except Exception:
        return False


def hash_password(password: str) -> str:
    return _password_hash(password)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_default_user(db: Session) -> User | None:
    org = ensure_default_organization(db)
    try:
        user = db.query(User).filter(User.email.in_([DEFAULT_USER_EMAIL, "owner@nagacon.local"])).first()
        if user:
            if org is not None and user.organization_id != org.id:
                user.organization_id = org.id
            if user.email != DEFAULT_USER_EMAIL:
                user.email = DEFAULT_USER_EMAIL
            if getattr(user, "full_name", None) in {None, "", "Default Owner"}:
                user.full_name = DEFAULT_USER_NAME
            if not verify_password(DEFAULT_USER_PASSWORD, getattr(user, "password_hash", None)):
                user.password_hash = hash_password(DEFAULT_USER_PASSWORD)
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        user = User(
            email=DEFAULT_USER_EMAIL,
            full_name=DEFAULT_USER_NAME,
            role=DEFAULT_USER_ROLE,
            organization_id=getattr(org, "id", None),
            password_hash=hash_password(DEFAULT_USER_PASSWORD),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None


def get_or_create_user_by_email(db: Session, email: str | None) -> User | None:
    normalized = _normalize_email(email)
    if not normalized:
        return ensure_default_user(db)
    org = ensure_default_organization(db)
    try:
        user = db.query(User).filter(User.email == normalized).first()
        if user:
            if org is not None and user.organization_id is None:
                user.organization_id = org.id
                db.add(user)
                db.commit()
                db.refresh(user)
            return user
        display_name = normalized.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
        user = User(
            email=normalized,
            full_name=display_name or DEFAULT_USER_NAME,
            role="MEMBER",
            organization_id=getattr(org, "id", None),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return ensure_default_user(db)


def get_user_by_session_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    token_hash = hash_session_token(token)
    now = _utcnow()
    try:
        user = db.query(User).filter(User.session_token_hash == token_hash, User.is_active.is_(True)).first()
        if not user:
            return None
        expires_at = getattr(user, "session_expires_at", None)
        if expires_at and expires_at < now:
            clear_user_session(db, user, commit=True)
            return None
        return user
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None


def create_user_account(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    role: str = "OWNER",
) -> User:
    normalized = _normalize_email(email)
    if not normalized:
        raise ValueError("Email is required")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    existing = db.query(User).filter(User.email == normalized).first()
    if existing:
        raise ValueError("An account with that email already exists")
    org = ensure_default_organization(db)
    user = User(
        email=normalized,
        full_name=(full_name or normalized.split("@", 1)[0]).strip() or DEFAULT_USER_NAME,
        role=role,
        organization_id=getattr(org, "id", None),
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, identifier: str, password: str) -> User | None:
    normalized = _normalize_identifier(identifier)
    if not normalized or not password:
        return None
    try:
        user = db.query(User).filter(User.email == normalized).first()
        if not user and "@" not in normalized:
            local_part = f"{normalized}@nagacon.local"
            user = db.query(User).filter(User.email.in_([local_part, f"{normalized}@gmail.com"])).first()
        if not user and normalized == DEFAULT_USER_USERNAME:
            user = ensure_default_user(db)
        if not user or not getattr(user, "is_active", True):
            return None
        if not verify_password(password, getattr(user, "password_hash", None)):
            return None
        return user
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None


def start_user_session(db: Session, user: User) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = _utcnow() + timedelta(days=SESSION_TTL_DAYS)
    user.session_token_hash = hash_session_token(token)
    user.session_expires_at = expires_at
    db.add(user)
    db.commit()
    db.refresh(user)
    return token, expires_at


def clear_user_session(db: Session, user: User, *, commit: bool = True) -> User:
    user.session_token_hash = None
    user.session_expires_at = None
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
    return user
