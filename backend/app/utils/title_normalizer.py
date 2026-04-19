from __future__ import annotations

from datetime import datetime
import re
from typing import Any

EM_DASH = " - "


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean(text: str | None) -> str | None:
    text = _safe(text)
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()


def _normalize_nsn(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
    return value


def _humanize_phrase(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    value = re.sub(r"\s*,\s*", ", ", value)
    if re.fullmatch(r"[A-Z0-9 ,./()&-]+", value) and re.search(r"[A-Z]", value):
        value = value.title()
    return value


def _humanize_quantity(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    try:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
    except Exception:
        pass
    return value


def _humanize_date(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    for pattern in ("%Y %b %d", "%Y %B %d", "%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized.title(), pattern)
            return parsed.strftime("%b %d, %Y")
        except Exception:
            continue
    return normalized.title()


def _dibbs_title(
    *,
    raw_title: str | None,
    solicitation_number: str | None,
    source_opportunity_id: str | None,
    raw_payload: dict[str, Any] | None,
    parsed_json: dict[str, Any] | None,
    raw_text: str | None,
) -> str:
    raw_payload = raw_payload or {}
    parsed_json = parsed_json or {}
    dibbs_detail = raw_payload.get("dibbs_detail") or {}
    item_signals = raw_payload.get("item_signals") or {}

    nomenclature = (
        _clean(parsed_json.get("nomenclature"))
        or _clean(dibbs_detail.get("nomenclature"))
        or _clean(raw_payload.get("nomenclature"))
    )

    if not nomenclature and raw_text:
        m = re.search(r"Item:\s*([^|]+)", raw_text, re.IGNORECASE)
        if m:
            cand = _clean(m.group(1))
            if cand:
                nomenclature = cand

    nsn = (
        _normalize_nsn(source_opportunity_id)
        or _normalize_nsn(solicitation_number)
        or _normalize_nsn(parsed_json.get("nsn"))
        or _normalize_nsn(dibbs_detail.get("nsn"))
        or _normalize_nsn(item_signals.get("nsn"))
        or _normalize_nsn(raw_title)
    )

    if nomenclature and nsn and nomenclature != nsn:
        return f"{nomenclature}{EM_DASH}{nsn}"
    if nomenclature:
        return nomenclature
    if nsn:
        return f"DIBBS RFQ{EM_DASH}{nsn}"
    return _clean(raw_title) or "DIBBS RFQ"


def _sam_title(*, raw_title: str | None, solicitation_number: str | None) -> str:
    clean_title = _clean(raw_title) or "SAM Opportunity"
    sol = _clean(solicitation_number)

    if len(clean_title) > 140:
        clean_title = clean_title[:137].rstrip() + "..."

    if sol and sol not in clean_title:
        return f"{sol}{EM_DASH}{clean_title}"
    return clean_title


def normalize_title(
    *,
    source: str | None,
    raw_title: str | None = None,
    solicitation_number: str | None = None,
    source_opportunity_id: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    parsed_json: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> str:
    source_up = (source or "").upper()
    if source_up == "DIBBS":
        return _dibbs_title(
            raw_title=raw_title,
            solicitation_number=solicitation_number,
            source_opportunity_id=source_opportunity_id,
            raw_payload=raw_payload,
            parsed_json=parsed_json,
            raw_text=raw_text,
        )
    if source_up == "SAM":
        return _sam_title(raw_title=raw_title, solicitation_number=solicitation_number)
    return _clean(raw_title) or solicitation_number or source_opportunity_id or "Opportunity"


def normalize_source_title(
    *,
    source: str | None,
    title: str | None = None,
    raw_title: str | None = None,
    solicitation_number: str | None = None,
    source_opportunity_id: str | None = None,
    description: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    parsed_json: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> str:
    return normalize_title(
        source=source,
        raw_title=raw_title if raw_title is not None else title,
        solicitation_number=solicitation_number,
        source_opportunity_id=source_opportunity_id,
        raw_payload=raw_payload,
        parsed_json=parsed_json,
        raw_text=raw_text if raw_text is not None else description,
    )


def normalize_titles(
    *,
    source: str | None,
    raw_title: str | None,
    solicitation_number: str | None = None,
    source_opportunity_id: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    parsed_json: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> dict[str, str]:
    display = normalize_title(
        source=source,
        raw_title=raw_title,
        solicitation_number=solicitation_number,
        source_opportunity_id=source_opportunity_id,
        raw_payload=raw_payload,
        parsed_json=parsed_json,
        raw_text=raw_text,
    )
    return {
        "display_title": display,
        "source_uniform_title": display,
    }


def build_summary_text(
    raw_text: str | None,
    parsed_json: dict[str, Any] | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> str | None:
    parsed_json = parsed_json or {}
    raw_payload = raw_payload or {}
    nsn = _normalize_nsn(parsed_json.get("nsn"))
    nomenclature = _humanize_phrase(parsed_json.get("nomenclature") or parsed_json.get("item_description"))
    solicitation_rows = parsed_json.get("solicitations") or []
    primary_row = solicitation_rows[0] if solicitation_rows else {}
    quantity = _humanize_quantity(primary_row.get("qty"))
    due = _humanize_date(primary_row.get("return_by_date"))

    if nomenclature or nsn or quantity or due:
        if quantity and nomenclature:
            first_sentence = f"This opportunity appears to request quotes for {quantity} units of {nomenclature}"
        elif nomenclature:
            first_sentence = f"This opportunity appears to request quotes for {nomenclature}"
        else:
            first_sentence = "This opportunity appears to request quotes for the referenced item"
        if nsn:
            first_sentence += f" (NSN {nsn})"
        first_sentence += "."

        if due:
            return f"{first_sentence} Responses are due by {due}."
        return first_sentence

    if raw_text:
        txt = _clean(raw_text)
        if txt:
            return txt[:500]

    return None
