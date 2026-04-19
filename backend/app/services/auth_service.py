from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.organization import User
from app.services.org_service import ensure_default_organization


DEFAULT_USER_EMAIL = "owner@nagacon.local"
DEFAULT_USER_NAME = "Default Owner"
DEFAULT_USER_ROLE = "OWNER"


def ensure_default_user(db: Session) -> User | None:
    org = ensure_default_organization(db)
    try:
        user = db.query(User).filter(User.email == DEFAULT_USER_EMAIL).first()
        if user:
            if org is not None and user.organization_id != org.id:
                user.organization_id = org.id
                db.add(user)
                db.commit()
                db.refresh(user)
            return user
        user = User(
            email=DEFAULT_USER_EMAIL,
            full_name=DEFAULT_USER_NAME,
            role=DEFAULT_USER_ROLE,
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
        return None


def get_or_create_user_by_email(db: Session, email: str | None) -> User | None:
    if not email:
        return ensure_default_user(db)
    normalized = email.strip().lower()
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
