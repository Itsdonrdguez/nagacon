from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.schemas.opportunity import RawOpportunity


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == {} or value == []


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_existing(db: Session, raw: RawOpportunity) -> Opportunity | None:
    solicitation_number = _safe(getattr(raw, "solicitation_number", None))
    url = _safe(getattr(raw, "url", None))

    if solicitation_number:
        existing = db.query(Opportunity).filter(Opportunity.solicitation_number == solicitation_number).first()
        if existing:
            return existing

    if url:
        existing = db.query(Opportunity).filter(Opportunity.url == url).first()
        if existing:
            return existing

    return None


def _copy_field(existing: Opportunity, raw: RawOpportunity, field_name: str, force_refresh: bool) -> bool:
    incoming = getattr(raw, field_name, None)
    current = getattr(existing, field_name, None)

    if _is_blank(incoming):
        return False

    if force_refresh:
        if _is_blank(current) or current != incoming:
            setattr(existing, field_name, incoming)
            return True
        return False

    if _is_blank(current):
        setattr(existing, field_name, incoming)
        return True

    return False


def upsert_raw_opportunity(db: Session, raw: RawOpportunity, force_refresh: bool = False) -> str:
    existing = _find_existing(db, raw)

    if existing:
        changed = False

        for field_name in [
            "source",
            "source_opportunity_id",
            "solicitation_number",
            "title",
            "agency",
            "url",
            "posted_at",
            "due_at",
            "naics_code",
            "fsc_code",
            "description",
            "raw_payload",
        ]:
            changed = _copy_field(existing, raw, field_name, force_refresh) or changed

        if changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return "updated"

        return "skipped"

    rec = Opportunity(
        source=getattr(raw, "source", None),
        source_opportunity_id=getattr(raw, "source_opportunity_id", None),
        solicitation_number=getattr(raw, "solicitation_number", None),
        title=getattr(raw, "title", None),
        agency=getattr(raw, "agency", None),
        url=getattr(raw, "url", None),
        posted_at=getattr(raw, "posted_at", None),
        due_at=getattr(raw, "due_at", None),
        naics_code=getattr(raw, "naics_code", None),
        fsc_code=getattr(raw, "fsc_code", None),
        description=getattr(raw, "description", None),
        raw_payload=getattr(raw, "raw_payload", None),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return "inserted"


def _clean_saved_title(value: str | None) -> str | None:
    if value is None:
        return value
    return (
        value.replace("â€”", "-")
        .replace("â€“", "-")
        .replace("â€", "")
        .replace("â", "-")
    )
