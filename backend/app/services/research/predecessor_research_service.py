
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead

USASPENDING_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
SAM_OPPORTUNITIES_URL = "https://api.sam.gov/opportunities/v2/search"


class ResearchError(RuntimeError):
    pass


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _keyword_tokens(*parts: Any, limit: int = 8) -> list[str]:
    text = " ".join([_clean(x) or "" for x in parts]).lower()
    tokens = re.findall(r"\b[a-z0-9][a-z0-9\-/]{2,}\b", text)
    stop = {
        "the", "and", "for", "with", "solicitation", "combined", "notice", "award",
        "contract", "dla", "agency", "inc", "llc", "corp", "medical", "supply", "supplies",
    }
    out: list[str] = []
    seen = set()
    for token in tokens:
        if token in stop or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _opp_context(opp: Opportunity) -> dict[str, Any]:
    parsed = getattr(opp, "parsed_json", None) or {}
    raw_payload = getattr(opp, "raw_payload", None) or {}

    nsn = parsed.get("nsn") or raw_payload.get("nsn") or None
    naics = getattr(opp, "naics", None) or raw_payload.get("naics") or None
    fsc = getattr(opp, "fsc", None) or raw_payload.get("fsc") or None
    agency = getattr(opp, "agency", None)
    title = getattr(opp, "title", None)
    solicitation_number = getattr(opp, "solicitation_number", None)

    keywords = _keyword_tokens(title, getattr(opp, "raw_text", None), nsn, fsc)

    return {
        "opportunity_id": opp.id,
        "solicitation_number": solicitation_number,
        "title": title,
        "agency": agency,
        "naics": naics,
        "fsc": fsc,
        "nsn": nsn,
        "keywords": keywords,
    }


def _usaspending_payload(context: dict[str, Any], limit: int = 25, lookback_years: int = 5) -> dict[str, Any]:
    today = date.today()
    start = date(today.year - lookback_years, today.month, today.day)

    filters: dict[str, Any] = {
        "award_type_codes": ["A", "B", "C", "D"],
        "time_period": [{"start_date": start.isoformat(), "end_date": today.isoformat()}],
    }

    if context.get("naics"):
        filters["naics_codes"] = [context["naics"]]

    # Keywords are the safest cross-source predecessor signal for DLA-style repeat buys.
    if context.get("keywords"):
        filters["keywords"] = context["keywords"][:5]

    return {
        "filters": filters,
        "fields": [
            "Award ID",
            "Recipient Name",
            "Awarding Agency",
            "Award Amount",
            "Start Date",
            "Last Modified Date",
            "Description",
            "generated_internal_id",
        ],
        "limit": limit,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
    }


def fetch_usaspending_awards(context: dict[str, Any], limit: int = 25, lookback_years: int = 5) -> list[dict[str, Any]]:
    payload = _usaspending_payload(context, limit=limit, lookback_years=lookback_years)
    response = requests.post(USASPENDING_SEARCH_URL, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("results", []) or []


def _sam_query_params(context: dict[str, Any], limit: int = 10) -> dict[str, Any] | None:
    api_key = os.getenv("SAM_API_KEY", "").strip()
    if not api_key:
        return None

    today = date.today()
    posted_from = (today - timedelta(days=365)).strftime("%m/%d/%Y")
    posted_to = today.strftime("%m/%d/%Y")

    params: dict[str, Any] = {
        "api_key": api_key,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": limit,
        "offset": 0,
    }

    if context.get("solicitation_number"):
        params["solnum"] = context["solicitation_number"]
    elif context.get("title"):
        params["title"] = context["title"][:120]

    return params


def fetch_related_sam_opportunities(context: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    params = _sam_query_params(context, limit=limit)
    if not params:
        return []
    response = requests.get(SAM_OPPORTUNITIES_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("opportunitiesData", []) or data.get("data", []) or []


def rank_vendors_from_awards(context: dict[str, Any], awards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "vendor": None,
        "award_count": 0,
        "total_award_amount": 0.0,
        "last_award_date": None,
        "agencies": set(),
        "sample_awards": [],
        "score": 0,
        "match_reasons": [],
    })

    agency_hint = (_clean(context.get("agency")) or "").lower()
    title_terms = set([x.lower() for x in context.get("keywords") or []])

    for award in awards:
        vendor = _clean(award.get("Recipient Name"))
        if not vendor:
            continue

        awarding_agency = _clean(award.get("Awarding Agency"))
        amount = award.get("Award Amount") or 0
        try:
            amount = float(amount)
        except Exception:
            amount = 0.0

        start_date = _clean(award.get("Start Date"))
        desc = (_clean(award.get("Description")) or "").lower()
        desc_terms = set(re.findall(r"\b[a-z0-9][a-z0-9\-/]{2,}\b", desc))

        entry = groups[vendor]
        entry["vendor"] = vendor
        entry["award_count"] += 1
        entry["total_award_amount"] += amount
        if awarding_agency:
            entry["agencies"].add(awarding_agency)
        if len(entry["sample_awards"]) < 3:
            entry["sample_awards"].append({
                "award_id": award.get("Award ID"),
                "amount": amount,
                "agency": awarding_agency,
                "start_date": start_date,
            })
        if start_date and ((entry["last_award_date"] is None) or (start_date > entry["last_award_date"])):
            entry["last_award_date"] = start_date

        score = 0
        reasons: list[str] = []

        if agency_hint and awarding_agency and agency_hint in awarding_agency.lower():
            score += 35
            reasons.append("same agency")

        term_overlap = len(title_terms.intersection(desc_terms))
        if term_overlap:
            score += min(25, term_overlap * 5)
            reasons.append(f"keyword overlap ({term_overlap})")

        score += min(20, entry["award_count"] * 4)
        if amount > 0:
            score += 10
            reasons.append("has paid awards")

        entry["score"] += score
        entry["match_reasons"].extend(reasons)

    ranked = []
    for entry in groups.values():
        deduped_reasons = []
        seen = set()
        for reason in entry["match_reasons"]:
            if reason in seen:
                continue
            seen.add(reason)
            deduped_reasons.append(reason)
        ranked.append({
            "vendor": entry["vendor"],
            "award_count": entry["award_count"],
            "total_award_amount": round(entry["total_award_amount"], 2),
            "last_award_date": entry["last_award_date"],
            "agencies": sorted(entry["agencies"]),
            "score": entry["score"],
            "match_reasons": deduped_reasons,
            "sample_awards": entry["sample_awards"],
        })

    ranked.sort(key=lambda x: (x["score"], x["award_count"], x["total_award_amount"]), reverse=True)
    return ranked


def run_predecessor_research(db: Session, opportunity_id: int, top_vendors: int = 25, lookback_years: int = 5) -> dict[str, Any]:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ResearchError("Opportunity not found")

    context = _opp_context(opp)
    awards = fetch_usaspending_awards(context, limit=50, lookback_years=lookback_years)
    ranked_vendors = rank_vendors_from_awards(context, awards)[:top_vendors]
    sam_related = fetch_related_sam_opportunities(context, limit=10)

    return {
        "opportunity_id": opportunity_id,
        "research_context": context,
        "usaspending_awards_found": len(awards),
        "historical_awards": awards[:20],
        "likely_vendors": ranked_vendors,
        "sam_related_opportunities": sam_related,
        "sam_enabled": bool(os.getenv("SAM_API_KEY", "").strip()),
    }


def seed_vendor_leads_from_research(db: Session, opportunity_id: int, vendor_rows: list[dict[str, Any]]) -> dict[str, Any]:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ResearchError("Opportunity not found")

    created = 0
    updated = 0

    for row in vendor_rows:
        company_name = _clean(row.get("vendor"))
        if not company_name:
            continue

        existing = (
            db.query(VendorLead)
            .filter(VendorLead.opportunity_id == opportunity_id)
            .filter(VendorLead.company_name == company_name)
            .first()
        )

        notes = (
            f"Seeded from USAspending research. Award count={row.get('award_count')}; "
            f"total_award_amount={row.get('total_award_amount')}; "
            f"last_award_date={row.get('last_award_date')}; "
            f"reasons={', '.join(row.get('match_reasons') or [])}"
        )

        confidence = min(95, max(55, int(row.get("score", 0))))

        if existing:
            touched = False
            if not existing.notes:
                existing.notes = notes
                touched = True
            if not existing.raw_text:
                existing.raw_text = str(row)
                touched = True
            if confidence > (existing.confidence or 0):
                existing.confidence = confidence
                touched = True
            if touched:
                updated += 1
            continue

        db.add(VendorLead(
            opportunity_id=opportunity_id,
            source_type="USASPENDING_RESEARCH",
            company_name=company_name,
            cage=None,
            part_number=None,
            nsn=_clean((_opp_context(opp)).get("nsn")),
            status="NEW",
            confidence=confidence,
            is_approved_source=False,
            raw_text=str(row),
            notes=notes,
        ))
        created += 1

    if created or updated:
        db.commit()

    return {
        "created": created,
        "updated": updated,
        "vendor_count_considered": len(vendor_rows),
    }
