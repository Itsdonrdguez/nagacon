from __future__ import annotations

from typing import Any

import requests

USASPENDING_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
HTTP_TIMEOUT = 30


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_keywords(keywords: list[str] | None) -> list[str]:
    if not keywords:
        return []
    out: list[str] = []
    for kw in keywords:
        text = _safe(kw)
        if text:
            out.append(text)
    return out[:8]


def _fields() -> list[str]:
    return [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Start Date",
        "End Date",
        "Award Type",
        "Description",
    ]


def _base_filters(naics_code: str | None = None) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "award_type_codes": ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13"],
    }
    code = _safe(naics_code)
    if code:
        filters["naics_codes"] = [code]
    return filters


def build_vendor_intelligence_payload(
    *,
    naics_code: str | None = None,
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    filters = _base_filters(naics_code=naics_code)
    cleaned_keywords = _clean_keywords(keywords)
    agency = _safe(awarding_agency)

    if cleaned_keywords:
        filters["keywords"] = cleaned_keywords
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]

    return {
        "filters": filters,
        "fields": _fields(),
        "page": page,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def _post_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(USASPENDING_SEARCH_URL, json=payload, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _candidate_payloads(
    *,
    naics_code: str | None = None,
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    page: int = 1,
    limit: int = 10,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []

    payloads.append(
        build_vendor_intelligence_payload(
            naics_code=naics_code,
            keywords=keywords,
            awarding_agency=awarding_agency,
            page=page,
            limit=limit,
        )
    )
    payloads.append(
        build_vendor_intelligence_payload(
            naics_code=naics_code,
            keywords=keywords,
            awarding_agency=None,
            page=page,
            limit=limit,
        )
    )
    payloads.append(
        build_vendor_intelligence_payload(
            naics_code=naics_code,
            keywords=None,
            awarding_agency=awarding_agency,
            page=page,
            limit=limit,
        )
    )
    payloads.append(
        build_vendor_intelligence_payload(
            naics_code=naics_code,
            keywords=None,
            awarding_agency=None,
            page=page,
            limit=limit,
        )
    )

    import json as _json
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for payload in payloads:
        key = _json.dumps(payload, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(payload)
    return unique


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("Recipient Name"),
        "uei": row.get("Recipient UEI"),
        "award_amount": row.get("Award Amount"),
        "awarding_agency": row.get("Awarding Agency"),
        "awarding_sub_agency": row.get("Awarding Sub Agency"),
        "award_id": row.get("Award ID"),
        "award_type": row.get("Award Type"),
        "start_date": row.get("Start Date"),
        "end_date": row.get("End Date"),
        "description": row.get("Description"),
    }


def find_similar_awardees(
    *,
    naics_code: str | None = None,
    keywords: list[str] | None = None,
    awarding_agency: str | None = None,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    last_error: str | None = None
    used_payload: dict[str, Any] | None = None
    data: dict[str, Any] | None = None

    for payload in _candidate_payloads(
        naics_code=naics_code,
        keywords=keywords,
        awarding_agency=awarding_agency,
        page=page,
        limit=limit,
    ):
        used_payload = payload
        try:
            data = _post_payload(payload)
            break
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 400:
                try:
                    last_error = response.text
                except Exception:
                    last_error = str(exc)
                continue
            raise

    if data is None:
        raise ValueError(f"USAspending search failed after fallbacks: {last_error or 'unknown 400 error'}")

    results = [_normalize_row(row) for row in data.get("results", [])]
    return {
        "query": {
            "naics_code": naics_code,
            "keywords": keywords or [],
            "awarding_agency": awarding_agency,
            "page": page,
            "limit": limit,
        },
        "used_payload": used_payload,
        "results": results,
        "page_metadata": data.get("page_metadata", {}),
    }
