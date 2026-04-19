from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.organization import Organization


DEFAULT_ORG_NAME = "Default Organization"
DEFAULT_ORG_SLUG = "default"


def get_default_organization(db: Session) -> Organization | None:
    try:
        org = db.query(Organization).filter(Organization.is_default.is_(True)).first()
        if org:
            return org
        org = db.query(Organization).order_by(Organization.id.asc()).first()
        return org
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None


def ensure_default_organization(db: Session) -> Organization | None:
    org = get_default_organization(db)
    if org:
        return org
    try:
        org = Organization(name=DEFAULT_ORG_NAME, slug=DEFAULT_ORG_SLUG, is_default=True)
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return None
