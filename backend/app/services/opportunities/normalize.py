from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.schemas.opportunity import OpportunityCreate, RawOpportunity
from app.utils.exceptions import NormalizationError
from app.utils.title_normalizer import normalize_source_title


UTC = ZoneInfo("UTC")


def safe_parse_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


def safe_str(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_raw_opportunity(raw: RawOpportunity) -> OpportunityCreate:
    normalized_title = normalize_source_title(
        source=raw.source,
        title=raw.title,
        solicitation_number=raw.solicitation_number,
        source_opportunity_id=raw.source_opportunity_id,
        description=raw.description,
        raw_payload=raw.raw_payload,
    )
    if not normalized_title:
        raise NormalizationError(
            f"Missing title for {raw.source}/{raw.source_opportunity_id or raw.solicitation_number or 'unknown'}"
        )

    solicitation_number = safe_str(raw.solicitation_number)
    source_id = safe_str(raw.source_opportunity_id)
    if not solicitation_number and source_id:
        solicitation_number = source_id

    return OpportunityCreate(
        source=safe_str(raw.source) or "unknown",
        source_opportunity_id=source_id,
        solicitation_number=solicitation_number,
        title=normalized_title,
        agency=safe_str(raw.agency),
        sub_agency=safe_str(raw.sub_agency),
        office=safe_str(raw.office),
        url=safe_str(raw.url),
        posted_at=safe_parse_datetime(raw.posted_at),
        due_at=safe_parse_datetime(raw.due_at),
        set_aside_type=safe_str(raw.set_aside_type),
        naics_code=safe_str(raw.naics_code),
        fsc_code=safe_str(raw.fsc_code),
        place_of_performance=safe_str(raw.place_of_performance),
        description=safe_str(raw.description),
        raw_payload=raw.raw_payload,
        status="new",
    )
