from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from app.schemas.opportunity import RawOpportunity
from app.services.dibbs.custom_query_search import search_dibbs_custom_query_by_fsc
from app.services.dibbs_adapter import pull_dibbs_by_fsc


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_spaces(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def _extract_dibbs_value(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        value = qs.get("value", [None])[0]
        return _safe(value)
    except Exception:
        return None


def _normalize_nsn(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
    return value


def _normalize_fsc(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    m = re.search(r"\b(\d{4})\b", value)
    return m.group(1) if m else value


def _normalize_sol(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    return value.replace("-", "").upper()


def _extract_nsn_from_url_or_text(url: str | None, title: str | None = None) -> str | None:
    url_value = _extract_dibbs_value(url)
    if url_value and re.fullmatch(r"\d{13}", re.sub(r"\D", "", url_value)):
        return _normalize_nsn(url_value)

    text = " ".join([x for x in [url or "", title or ""] if x])
    m = re.search(r"\b(\d{13})\b", text)
    if m:
        return _normalize_nsn(m.group(1))
    m = re.search(r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b", text)
    if m:
        return m.group(1)
    return None


def _derive_item_signals(title: str | None, url: str | None, fsc: str | None) -> dict[str, Any]:
    title_text = _clean_spaces(title) or ""
    title_upper = title_text.upper()
    dibbs_value = _extract_dibbs_value(url)
    nsn = _extract_nsn_from_url_or_text(url, title_text)

    tokens = re.findall(r"[A-Z0-9]{3,}", title_upper)
    keywords = []
    seen = set()
    stop = {"DLA", "DIBBS", "THE", "AND", "FOR"}
    for tok in tokens:
        if tok in stop:
            continue
        if tok not in seen:
            seen.add(tok)
            keywords.append(tok)

    product_family = " ".join(keywords[:3]) if len(keywords) >= 2 else None

    return {
        "nsn": nsn,
        "fsc_code": _normalize_fsc(fsc),
        "dibbs_value": dibbs_value,
        "product_family": product_family,
        "title_keywords": keywords[:8],
    }


def fetch_dibbs_opportunities(params: Optional[Dict] = None, max_pages: int = 1) -> List[RawOpportunity]:
    params = params or {}
    fsc_value = _safe(params.get("fsc") or params.get("fsc_code"))
    limit = int(params.get("limit") or params.get("page_size") or 25)
    debug = bool(params.get("debug", False))
    use_legacy = bool(params.get("legacy", False))
    include_past_due = bool(params.get("include_past_due", False))
    all_results = bool(params.get("all_results", False))

    if not use_legacy:
        rows, diagnostics = search_dibbs_custom_query_by_fsc(
            fsc=fsc_value or "",
            limit=limit,
            max_pages=max_pages,
            include_past_due=include_past_due,
            all_results=all_results,
            headless=not debug,
        )
        raw_records: List[RawOpportunity] = []
        for row in rows:
            nsn = _normalize_nsn(row.get("nsn"))
            rfq_number = _normalize_sol(row.get("solicitation_number"))
            display_identifier = nsn or rfq_number or row.get("nomenclature") or "DIBBS-RFQ"
            source_identifier = rfq_number or nsn or row.get("nomenclature") or "DIBBS-RFQ"
            title = _clean_spaces(row.get("nomenclature")) or nsn or rfq_number or display_identifier
            description_bits = []
            if title:
                description_bits.append(f"Item: {title}")
            if nsn:
                description_bits.append(f"NSN: {nsn}")
            if fsc_value:
                description_bits.append(f"FSC: {fsc_value}")
            if row.get("quantity"):
                description_bits.append(f"QTY: {row.get('quantity')}")
            if row.get("pr_number"):
                description_bits.append(f"PR: {row.get('pr_number')}")

            raw_records.append(
                RawOpportunity(
                    source="DIBBS",
                    source_opportunity_id=source_identifier,
                    solicitation_number=display_identifier,
                    title=title,
                    agency="DLA (DIBBS)",
                    sub_agency=None,
                    office=None,
                    url=row.get("package_url") or row.get("pdf_url") or row.get("detail_url") or "",
                    posted_at=row.get("issue_date"),
                    due_at=row.get("return_by_date"),
                    set_aside_type=None,
                    naics_code=None,
                    fsc_code=_normalize_fsc(fsc_value or nsn),
                    place_of_performance=None,
                    description=" | ".join(description_bits) if description_bits else title,
                    raw_payload={
                        "source_adapter": "dibbs_custom_query_fsc",
                        "dibbs_search_row": {
                            **{key: value for key, value in row.items() if key != "return_by_parsed"},
                        },
                        "dibbs_diagnostics": diagnostics,
                        "item_signals": {
                            **_derive_item_signals(title, row.get("detail_url"), fsc_value),
                            "rfq_number": rfq_number,
                        },
                    },
                )
            )
        return raw_records

    items, diagnostics = pull_dibbs_by_fsc(fsc=fsc_value, limit=limit, debug=debug)
    raw_records: List[RawOpportunity] = []

    for item in items:
        detail_url = _safe(item.get("detail_url") or item.get("url"))
        title = _clean_spaces(item.get("title")) or "DIBBS RFQ"
        source_opp_id = _normalize_nsn(item.get("source_opportunity_id")) or _extract_nsn_from_url_or_text(detail_url, title)
        solicitation_number = _normalize_nsn(item.get("solicitation_number")) or source_opp_id or title

        item_raw_payload = item.get("raw_payload") or {}
        dibbs_detail = item_raw_payload.get("dibbs_detail") if isinstance(item_raw_payload, dict) else None

        # IMPORTANT: keep raw_payload flat and serializable only
        raw_payload: dict[str, Any] = {
            "source_adapter": "pull_dibbs_by_fsc",
            "item_signals": _derive_item_signals(title, detail_url, fsc_value),
        }
        if isinstance(dibbs_detail, dict) and dibbs_detail:
            raw_payload["dibbs_detail"] = dibbs_detail

        nomenclature = _clean_spaces((dibbs_detail or {}).get("nomenclature")) if isinstance(dibbs_detail, dict) else None
        if nomenclature and re.fullmatch(r"[0-9\-]+", nomenclature):
            nomenclature = None
        if not nomenclature and title != solicitation_number:
            nomenclature = title

        description_bits = []
        if nomenclature:
            description_bits.append(f"Item: {nomenclature}")
        if source_opp_id:
            description_bits.append(f"NSN: {source_opp_id}")
        if fsc_value:
            description_bits.append(f"FSC: {fsc_value}")

        raw_records.append(
            RawOpportunity(
                source="DIBBS",
                source_opportunity_id=source_opp_id,
                solicitation_number=solicitation_number or source_opp_id or title,
                title=title,
                agency=_clean_spaces(item.get("agency")) or "DLA (DIBBS)",
                sub_agency=_clean_spaces(item.get("sub_agency")),
                office=_clean_spaces(item.get("office")),
                url=detail_url or "",
                posted_at=item.get("posted_at"),
                due_at=item.get("due_at"),
                set_aside_type=_clean_spaces(item.get("set_aside_type")),
                naics_code=_clean_spaces(item.get("naics_code")),
                fsc_code=_normalize_fsc(item.get("fsc_code") or fsc_value),
                place_of_performance=_clean_spaces(item.get("place_of_performance")),
                description=" | ".join(description_bits) if description_bits else (title or "DIBBS RFQ"),
                raw_payload=raw_payload,
            )
        )

    return raw_records
