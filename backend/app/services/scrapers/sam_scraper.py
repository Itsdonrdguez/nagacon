from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings
from app.schemas.opportunity import RawOpportunity

logger = logging.getLogger(__name__)


class SamScraperError(Exception):
    pass


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_naics(opp: dict[str, Any]) -> str | None:
    naics_block = opp.get("naics")
    if isinstance(naics_block, list) and naics_block:
        first = naics_block[0]
        if isinstance(first, dict):
            code_val = first.get("code")
            if isinstance(code_val, list):
                return _safe(code_val[0] if code_val else None)
            return _safe(code_val)
    return _safe(opp.get("naicsCode"))


def _extract_description(opp: dict[str, Any]) -> str | None:
    desc_block = opp.get("description")
    if isinstance(desc_block, list) and desc_block:
        first_desc = desc_block[0]
        if isinstance(first_desc, dict):
            return _safe(first_desc.get("body") or first_desc.get("description"))
    if isinstance(desc_block, str):
        return _safe(desc_block)
    return _safe(opp.get("descriptionText"))


def _extract_agency(opp: dict[str, Any]) -> str | None:
    org_info = opp.get("organizationInfo")
    if isinstance(org_info, list) and org_info:
        first_org = org_info[0]
        if isinstance(first_org, dict):
            return _safe(first_org.get("name"))
    elif isinstance(org_info, dict):
        return _safe(org_info.get("name"))
    return _safe(opp.get("fullParentPathName") or opp.get("department") or opp.get("agency"))


def _normalize_opp(opp: dict[str, Any]) -> RawOpportunity:
    source_id = _safe(opp.get("noticeId") or opp.get("id") or opp.get("opportunityId"))
    solicitation_number = _safe(
        opp.get("solicitationNumber") or opp.get("solNumber") or opp.get("solicitation")
    )
    title = _safe(opp.get("title")) or "SAM Opportunity"

    return RawOpportunity(
        source="SAM",
        source_opportunity_id=source_id,
        solicitation_number=solicitation_number,
        title=title,
        agency=_extract_agency(opp),
        posted_at=opp.get("postedDate") or opp.get("postedOn") or opp.get("publishDate"),
        due_at=opp.get("responseDeadLine") or opp.get("responseDate") or opp.get("archiveDate"),
        naics_code=_extract_naics(opp),
        fsc_code=_safe(opp.get("classificationCode") or opp.get("pscCode")),
        description=_extract_description(opp),
        url=_safe(opp.get("uiLink") or opp.get("link") or opp.get("url")),
        raw_payload=opp,
    )


def _fmt_mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _build_query_params(params: dict[str, Any], api_key: str) -> dict[str, Any]:
    today = date.today()
    posted_to = params.get("postedTo") or _fmt_mmddyyyy(today)
    posted_from = params.get("postedFrom") or _fmt_mmddyyyy(today - timedelta(days=30))

    query_params: dict[str, Any] = {
        "api_key": api_key,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": int(params.get("limit") or 10),
        "offset": int(params.get("offset") or 0),
    }

    # Official API expects named filters like title / solnum / noticeid, not freeform q.
    # Preserve q by mapping it to title when title is not already provided.
    if params.get("title"):
        query_params["title"] = params["title"]
    elif params.get("q"):
        query_params["title"] = params["q"]

    if params.get("noticeType"):
        query_params["ptype"] = params["noticeType"]
    elif params.get("ptype"):
        query_params["ptype"] = params["ptype"]

    if params.get("solnum"):
        query_params["solnum"] = params["solnum"]
    if params.get("noticeid"):
        query_params["noticeid"] = params["noticeid"]
    if params.get("state"):
        query_params["state"] = params["state"]
    if params.get("zip"):
        query_params["zip"] = params["zip"]
    if params.get("organizationCode"):
        query_params["organizationCode"] = params["organizationCode"]
    if params.get("organizationName"):
        query_params["organizationName"] = params["organizationName"]

    return query_params


def fetch_sam_opportunities(params: Optional[Dict] = None) -> List[RawOpportunity]:
    api_key = getattr(settings, "SAM_API_KEY", None)
    if not api_key:
        logger.warning("SAM_API_KEY not configured; returning empty SAM result set")
        return []

    base_url = "https://api.sam.gov/prod/opportunities/v2/search"
    params = params or {}
    query_params = _build_query_params(params, api_key)

    headers = {"Accept": "application/json"}
    bearer = getattr(settings, "SAM_BEARER_TOKEN", None)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    try:
        response = requests.get(base_url, params=query_params, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = None
        try:
            detail = response.text[:1000]
        except Exception:
            detail = None
        raise SamScraperError(
            f"SAM request failed: {exc}. params={query_params}. response={detail}"
        ) from exc
    except Exception as exc:
        raise SamScraperError(f"SAM request failed: {exc}. params={query_params}") from exc

    try:
        data = response.json()
    except Exception as exc:
        raise SamScraperError(f"SAM returned invalid JSON: {exc}") from exc

    opportunities = (
        data.get("_embedded", {}).get("opportunityList")
        or data.get("opportunitiesData")
        or data.get("opportunities")
        or []
    )

    raw_opps: List[RawOpportunity] = []
    seen: set[tuple[str | None, str | None]] = set()

    for opp in opportunities:
        raw = _normalize_opp(opp)
        key = (raw.source_opportunity_id, raw.solicitation_number)
        if key in seen:
            continue
        seen.add(key)
        raw_opps.append(raw)

    return raw_opps
