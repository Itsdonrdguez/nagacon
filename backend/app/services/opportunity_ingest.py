from __future__ import annotations

from typing import Any
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.schemas.opportunity import RawOpportunity
from app.services.org_service import ensure_default_organization
from app.services.opportunities.normalize import safe_parse_datetime

_STRING_LIMITS = {
    "source": 50,
    "source_opportunity_id": 120,
    "solicitation_number": 120,
    "title": 300,
    "agency": 200,
    "sub_agency": 200,
    "office": 200,
    "url": 500,
    "naics_code": 20,
    "fsc_code": 10,
    "set_aside_type": 80,
    "place_of_performance": 200,
}


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == {} or value == []


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prepare_value(field_name: str, value: Any) -> Any:
    if value is None:
        return None
    if field_name in {"posted_at", "due_at"}:
        return safe_parse_datetime(value)
    max_length = _STRING_LIMITS.get(field_name)
    if max_length is None:
        return value
    text = _safe(value)
    if text is None:
        return None
    return text[:max_length]


def _normalize_comparable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return value


def _find_existing(db: Session, raw: RawOpportunity) -> Opportunity | None:
    source = _safe(getattr(raw, "source", None))
    source_opportunity_id = _safe(getattr(raw, "source_opportunity_id", None))
    solicitation_number = _safe(getattr(raw, "solicitation_number", None))
    url = _safe(getattr(raw, "url", None))

    if source and source_opportunity_id:
        existing = db.query(Opportunity).filter(
            Opportunity.source == source,
            Opportunity.source_opportunity_id == source_opportunity_id,
        ).first()
        if existing:
            return existing

    if source and solicitation_number:
        existing = db.query(Opportunity).filter(
            Opportunity.source == source,
            Opportunity.solicitation_number == solicitation_number,
        ).first()
        if existing:
            return existing

    if source and url:
        existing = db.query(Opportunity).filter(
            Opportunity.source == source,
            Opportunity.url == url,
        ).first()
        if existing:
            return existing

    if solicitation_number:
        query = db.query(Opportunity).filter(Opportunity.solicitation_number == solicitation_number)
        if source:
            query = query.filter(Opportunity.source == source)
        existing = query.first()
        if existing:
            return existing

    if url:
        query = db.query(Opportunity).filter(Opportunity.url == url)
        if source:
            query = query.filter(Opportunity.source == source)
        existing = query.first()
        if existing:
            return existing

    return None


def _copy_field(existing: Opportunity, raw: RawOpportunity, field_name: str, force_refresh: bool) -> bool:
    incoming = _prepare_value(field_name, getattr(raw, field_name, None))
    current = getattr(existing, field_name, None)

    if _is_blank(incoming):
        return False

    if force_refresh:
        if _is_blank(current) or _normalize_comparable(current) != _normalize_comparable(incoming):
            setattr(existing, field_name, incoming)
            return True
        return False

    if _is_blank(current):
        setattr(existing, field_name, incoming)
        return True

    return False


def _copy_raw_payload(existing: Opportunity, raw: RawOpportunity, allow_refresh: bool) -> bool:
    incoming = _prepare_value("raw_payload", getattr(raw, "raw_payload", None))
    current = getattr(existing, "raw_payload", None)

    if _is_blank(incoming):
        return False

    if _is_blank(current):
        existing.raw_payload = incoming
        return True

    if allow_refresh and _normalize_comparable(current) != _normalize_comparable(incoming):
        existing.raw_payload = incoming
        return True

    return False


def _default_organization_id(db: Session) -> int | None:
    org = ensure_default_organization(db)
    return getattr(org, "id", None) if org else None


def upsert_raw_opportunity(
    db: Session,
    raw: RawOpportunity,
    force_refresh: bool = False,
    organization_id: int | None = None,
) -> str:
    organization_id = organization_id or _default_organization_id(db)
    existing = _find_existing(db, raw)

    if existing:
        changed = False
        if organization_id is not None and getattr(existing, "organization_id", None) is None:
            existing.organization_id = organization_id
            changed = True

        for field_name in [
            "source",
            "source_opportunity_id",
            "solicitation_number",
            "title",
            "agency",
            "sub_agency",
            "office",
            "url",
            "posted_at",
            "due_at",
            "set_aside_type",
            "naics_code",
            "fsc_code",
            "place_of_performance",
            "description",
        ]:
            changed = _copy_field(existing, raw, field_name, force_refresh) or changed

        # Raw/source payloads can contain volatile scraper details. Keep them for
        # new or genuinely refreshed records, but do not let payload-only churn
        # make every repeated search look like an updated opportunity.
        payload_changed = _copy_raw_payload(existing, raw, allow_refresh=changed)

        if changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return "updated"

        if payload_changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)

        return "skipped"

    rec = Opportunity(
        organization_id=organization_id,
        source=_prepare_value("source", getattr(raw, "source", None)),
        source_opportunity_id=_prepare_value("source_opportunity_id", getattr(raw, "source_opportunity_id", None)),
        solicitation_number=_prepare_value("solicitation_number", getattr(raw, "solicitation_number", None)),
        title=_prepare_value("title", getattr(raw, "title", None)),
        agency=_prepare_value("agency", getattr(raw, "agency", None)),
        sub_agency=_prepare_value("sub_agency", getattr(raw, "sub_agency", None)),
        office=_prepare_value("office", getattr(raw, "office", None)),
        url=_prepare_value("url", getattr(raw, "url", None)),
        posted_at=_prepare_value("posted_at", getattr(raw, "posted_at", None)),
        due_at=_prepare_value("due_at", getattr(raw, "due_at", None)),
        set_aside_type=_prepare_value("set_aside_type", getattr(raw, "set_aside_type", None)),
        naics_code=_prepare_value("naics_code", getattr(raw, "naics_code", None)),
        fsc_code=_prepare_value("fsc_code", getattr(raw, "fsc_code", None)),
        place_of_performance=_prepare_value("place_of_performance", getattr(raw, "place_of_performance", None)),
        description=_prepare_value("description", getattr(raw, "description", None)),
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
