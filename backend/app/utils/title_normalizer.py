from __future__ import annotations

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
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:13]}"
    return value


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

    bits: list[str] = []
    nsn = _normalize_nsn(parsed_json.get("nsn"))
    nomenclature = _clean(parsed_json.get("nomenclature"))
    if nomenclature:
        bits.append(nomenclature)
    if nsn:
        bits.append(f"NSN {nsn}")

    if raw_text:
        txt = _clean(raw_text)
        if txt and not bits:
            return txt[:500]
        if txt and txt not in " | ".join(bits):
            bits.append(txt[:300])

    if bits:
        return " | ".join(bits)
    return None
