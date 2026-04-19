from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnMaster, NsnReference
from app.models.opportunity import Opportunity
from app.models.price_history import PriceHistory
from app.models.vendor import VendorLead
from app.repositories.providers import ProviderRepository
from app.schemas.provider import ProviderCreate, ProviderItemCreate
from app.services.workspace_service import build_research_profile, ensure_parsed
from app.services.nsn_catalog.normalizer import normalize_nsn

USASPENDING_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
HTTP_TIMEOUT = 60

AGENCY_ALIASES: dict[str, list[str]] = {
    "DLA (DIBBS)": ["DEFENSE LOGISTICS AGENCY", "DEPARTMENT OF DEFENSE", "DEPT OF DEFENSE"],
    "DLA": ["DEFENSE LOGISTICS AGENCY", "DEPARTMENT OF DEFENSE"],
}

FSC_KEYWORD_MAP: dict[str, list[str]] = {
    "6520": [
        "dental", "preventive", "paste", "oral", "prophy", "prophylaxis", "tooth",
        "dentifrice", "polishing", "toothpaste"
    ],
    "6515": ["medical", "surgical", "device", "instrument", "catheter"],
    "6530": ["hospital", "patient", "ward", "medical"],
    "6505": ["pharmaceutical", "drug", "tablet", "capsule"],
}

DLA_6520_PRODUCT_TERMS = {
    "dentifrice", "toothpaste", "prophylaxis paste", "prophy paste",
    "dental paste", "polishing paste", "dental polishing paste",
    "oral prophylaxis", "fluoride varnish", "prophy", "tooth polishing",
}

STRICT_NEGATIVE_PRODUCT_TERMS = {
    "vaccine", "vaccines", "antigen", "diagnostic", "diagnostics", "respirator",
    "ventilator", "papr", "ppe", "test kit", "testing", "assay", "mask",
    "glove", "insurance", "benefits", "outpatient", "treatment", "clinic",
    "hospital", "construction", "joint venture", "maintenance", "hvac",
    "building", "facility", "facilities", "systems", "oracle health",
}

PRODUCT_POSITIVE_TERMS = {
    "dental", "oral", "paste", "prophy", "prophylaxis", "fluoride", "varnish",
    "toothpaste", "tooth", "preventive paste", "medical", "consumable",
    "supply item", "catheter", "bandage", "syringe", "instrument", "device",
    "antigen", "vaccine", "pharma", "pharmaceutical", "sterile", "medication",
    "approved source", "manufacturer", "nsn", "dentifrice", "polishing paste",
}

SERVICE_NOISE_TERMS = {
    "maintenance", "preventive maintenance", "corrective maintenance", "hvac",
    "facility", "facilities", "systems", "engineering", "operations",
    "support services", "electrical", "controls", "automation", "repair",
    "management services", "program", "building", "utility", "umcs", "scada",
    "surveillance", "training", "installation", "corrective", "integration",
    "project management", "logistical service", "support", "benefits",
}

HEALTH_SERVICE_NOISE_TERMS = {
    "outpatient", "treatment", "behavioral health", "clinic", "patient care",
    "health services", "medical services", "dental services", "insurance",
    "benefit plan", "benefits administration", "managed care",
}

SEED_BLOCK_VENDOR_TERMS = {
    "insurance", "concordia", "health services", "clinic", "hospital",
    "joint venture", "construction", "projects", "government services",
    "oracle health", "metropolitan life", "optum", "chartwell rx",
}


def _safe(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for v in values:
        x = _safe(v)
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _extract_nsn(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"\b(\d{4}-\d{2}-\d{3,})\b",
        r"\b(\d{13})\b",
        r"\bNSN[:\s]+(\d{4}-\d{2}-\d{3,})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _normalize_fsc(value: str | None) -> str:
    text = _safe(value)
    if not text:
        return ""
    digits = re.sub(r"\D+", "", text)
    return digits[:4] if len(digits) >= 4 else ""


def _fsc_from_nsn(nsn: str | None) -> str:
    return _normalize_fsc(nsn)


def _tokenize_keywords(text: str, limit: int = 12) -> list[str]:
    stop = {
        "the", "and", "for", "with", "this", "that", "from", "into", "shall", "will",
        "are", "you", "your", "their", "our", "have", "has", "not", "all", "any", "can",
        "may", "contract", "solicitation", "vendor", "quote", "proposal", "response",
        "requirement", "dla", "dibbs", "inc", "llc", "item", "supply", "supplies",
        "department", "defense", "agency", "request", "number", "spe2dh", "spe2ds",
        "sol", "rfq",
    }
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", text.lower())
    out: list[str] = []
    seen = set()
    for tok in tokens:
        if tok in stop or tok.isdigit() or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= limit:
            break
    return out


def _phrase_to_keywords(text: str, max_terms: int = 6) -> list[str]:
    return _tokenize_keywords(text, limit=max_terms)


def _agency_variants(agency: str) -> list[str]:
    agency = _safe(agency)
    variants = [agency]
    variants.extend(AGENCY_ALIASES.get(agency, []))
    if "DLA" in agency.upper() and "DEFENSE LOGISTICS AGENCY" not in variants:
        variants.extend(["DEFENSE LOGISTICS AGENCY", "DEPARTMENT OF DEFENSE"])
    return _dedupe_keep_order(variants)


def _preferred_nomenclature(parsed: dict[str, Any], title: str) -> str:
    candidates = [
        _safe(parsed.get("item_description")),
        _safe(parsed.get("nomenclature")),
        title,
    ]
    for c in candidates:
        if c and len(c) > len(title):
            return c
    return title


def _build_exact_item_terms(parsed: dict[str, Any], title: str, fsc: str) -> list[str]:
    terms: list[str] = []
    nomenclature = _preferred_nomenclature(parsed, title)
    terms.extend(_phrase_to_keywords(nomenclature, max_terms=8))
    if fsc:
        terms.append(fsc)

    for p in parsed.get("part_numbers") or []:
        p = _safe(p)
        if p and len(p) >= 3:
            terms.append(p)

    for m in parsed.get("manufacturers") or []:
        terms.extend(_phrase_to_keywords(_safe(m), max_terms=4))

    if fsc in FSC_KEYWORD_MAP:
        terms.extend(FSC_KEYWORD_MAP[fsc][:6])

    return _dedupe_keep_order(terms)


def _keyword_variants(title: str, raw_text: str, fsc: str, parsed: dict[str, Any]) -> list[list[str]]:
    base = _tokenize_keywords(f"{title} {raw_text}", limit=12)
    exact_terms = _build_exact_item_terms(parsed, title, fsc)
    fsc_words = FSC_KEYWORD_MAP.get(_safe(fsc), [])

    variants: list[list[str]] = []

    if parsed.get("nsn"):
        variants.append([parsed["nsn"]])

    if exact_terms:
        variants.append(exact_terms[:4])
        variants.append(exact_terms[:6])
        variants.append(_dedupe_keep_order(exact_terms[:3] + fsc_words[:4]))

    if fsc == "6520":
        variants.append(["dentifrice", "dental", "paste"])
        variants.append(["prophylaxis", "paste", "oral"])
        variants.append(["dental", "polishing", "paste"])

    if base:
        variants.append(base[:4])
        variants.append(base[:6])

    if fsc_words:
        variants.append(fsc_words[:5])

    title_words = _tokenize_keywords(title, limit=6)
    if title_words:
        variants.append(title_words)

    return [v for v in variants if v]


def _catalog_context_for_nsn(db: Session | None, nsn: str | None) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if db is None or not target:
        return {
            "catalog_item_name": "",
            "catalog_part_numbers": [],
            "catalog_manufacturers": [],
            "catalog_cages": [],
            "catalog_reference_count": 0,
        }
    try:
        master = db.query(NsnMaster).filter(NsnMaster.compact_nsn == target.compact).first()
        references = (
            db.query(NsnReference)
            .filter(NsnReference.compact_nsn == target.compact)
            .order_by(NsnReference.confidence.desc().nullslast())
            .limit(100)
            .all()
        )
    except Exception:
        return {
            "catalog_item_name": "",
            "catalog_part_numbers": [],
            "catalog_manufacturers": [],
            "catalog_cages": [],
            "catalog_reference_count": 0,
        }

    return {
        "catalog_item_name": _safe(getattr(master, "item_name", "")) if master else "",
        "catalog_part_numbers": _dedupe_keep_order([_safe(getattr(row, "part_number", "")) for row in references]),
        "catalog_manufacturers": _dedupe_keep_order([_safe(getattr(row, "company_name", "")) for row in references]),
        "catalog_cages": _dedupe_keep_order([_safe(getattr(row, "cage", "")) for row in references]),
        "catalog_reference_count": len(references),
    }


def _expand_context_with_catalog(ctx: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    item_name = _safe(catalog.get("catalog_item_name"))
    part_numbers = _dedupe_keep_order((ctx.get("part_numbers") or []) + (catalog.get("catalog_part_numbers") or []))
    manufacturers = _dedupe_keep_order((ctx.get("manufacturers") or []) + (catalog.get("catalog_manufacturers") or []))
    approved_names = _dedupe_keep_order((ctx.get("approved_source_names") or []) + (catalog.get("catalog_manufacturers") or []))
    approved_cages = _dedupe_keep_order((ctx.get("approved_source_cages") or []) + (catalog.get("catalog_cages") or []))

    if item_name:
        keywords = _dedupe_keep_order(_phrase_to_keywords(item_name, max_terms=8) + (ctx.get("keywords") or []))
        variants = [[item_name], _phrase_to_keywords(item_name, max_terms=6)] + (ctx.get("keyword_variants") or [])
        ctx["nomenclature"] = ctx.get("nomenclature") or item_name
    else:
        keywords = ctx.get("keywords") or []
        variants = ctx.get("keyword_variants") or []

    for part in part_numbers[:12]:
        if part:
            variants.insert(0, [part])
    for manufacturer in manufacturers[:8]:
        terms = _phrase_to_keywords(manufacturer, max_terms=4)
        if terms:
            variants.append(terms)

    nsn_target = normalize_nsn(ctx.get("nsn"))
    ctx.update(
        {
            "keywords": _dedupe_keep_order(keywords)[:30],
            "keyword_variants": _dedupe_keyword_lists(variants),
            "part_numbers": part_numbers,
            "manufacturers": manufacturers,
            "approved_source_names": approved_names,
            "approved_source_cages": approved_cages,
            "catalog_item_name": item_name,
            "catalog_part_numbers": catalog.get("catalog_part_numbers") or [],
            "catalog_manufacturers": catalog.get("catalog_manufacturers") or [],
            "catalog_cages": catalog.get("catalog_cages") or [],
            "catalog_reference_count": catalog.get("catalog_reference_count") or 0,
            "nsn_compact": nsn_target.compact if nsn_target else "",
            "niin": nsn_target.niin if nsn_target else "",
        }
    )
    return ctx


def _dedupe_keyword_lists(values: list[list[str]]) -> list[list[str]]:
    seen: set[str] = set()
    out: list[list[str]] = []
    for row in values:
        clean = _dedupe_keep_order([_safe(x) for x in row if _safe(x)])
        if not clean:
            continue
        key = "|".join(x.lower() for x in clean)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _opp_context(opp: Opportunity, db: Session | None = None) -> dict[str, Any]:
    title = _safe(getattr(opp, "title", ""))
    agency = _safe(getattr(opp, "agency", ""))
    naics = _safe(getattr(opp, "naics_code", getattr(opp, "naics", "")))
    fsc = _safe(getattr(opp, "fsc_code", getattr(opp, "fsc", "")))
    solicitation = _safe(getattr(opp, "solicitation_number", ""))
    raw_text = _safe(getattr(opp, "raw_text", ""))

    parsed = {}
    if db is not None:
        try:
            parsed = ensure_parsed(db, opp) or {}
        except Exception:
            parsed = _safe(getattr(opp, "parsed_json", "")) or {}
    elif isinstance(getattr(opp, "parsed_json", None), dict):
        parsed = getattr(opp, "parsed_json", {}) or {}

    if not isinstance(parsed, dict):
        parsed = {}

    nsn = _safe(parsed.get("nsn")) or _extract_nsn(raw_text) or _extract_nsn(title) or ""
    fsc = _normalize_fsc(fsc) or _fsc_from_nsn(nsn)
    nomenclature = _preferred_nomenclature(parsed, title)
    keywords = _build_exact_item_terms(parsed, nomenclature or title, fsc)
    if not keywords:
        keywords = _tokenize_keywords(f"{title} {raw_text}", limit=10)

    manufacturers = _dedupe_keep_order([_safe(x) for x in (parsed.get("manufacturers") or [])])
    part_numbers = _dedupe_keep_order([_safe(x) for x in (parsed.get("part_numbers") or []) if _safe(x)])
    approved_sources = parsed.get("approved_sources") or []
    solicitation_rows = parsed.get("solicitations") or []

    ctx = {
        "title": title,
        "agency": agency,
        "agency_variants": _agency_variants(agency),
        "naics_code": naics,
        "fsc_code": fsc,
        "solicitation_number": solicitation,
        "nsn": nsn,
        "keywords": keywords,
        "keyword_variants": _keyword_variants(nomenclature or title, raw_text, fsc, parsed),
        "nomenclature": nomenclature,
        "manufacturers": manufacturers,
        "part_numbers": part_numbers,
        "approved_sources": approved_sources,
        "solicitation_rows": solicitation_rows,
        "approved_source_names": _dedupe_keep_order([_safe(x.get("company_name")) for x in approved_sources if _safe(x.get("company_name"))]),
        "approved_source_cages": _dedupe_keep_order([_safe(x.get("cage")) for x in approved_sources if _safe(x.get("cage"))]),
    }
    return _expand_context_with_catalog(ctx, _catalog_context_for_nsn(db, nsn))


def _base_filters(lookback_years: int = 8) -> dict[str, Any]:
    start_date = (datetime.utcnow() - timedelta(days=365 * lookback_years)).strftime("%Y-%m-%d")
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    return {"award_type_codes": ["A", "B", "C", "D"], "time_period": [{"start_date": start_date, "end_date": end_date}]}


def _make_payload(filters: dict[str, Any], limit: int) -> dict[str, Any]:
    return {
        "filters": filters,
        "fields": ["Award ID", "Recipient Name", "Start Date", "Award Amount", "Awarding Agency", "Description"],
        "limit": limit,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
    }


def _query_plan(ctx: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    base = _base_filters()
    plans: list[dict[str, Any]] = []

    def add_plan(label: str, filters: dict[str, Any]):
        plans.append({"label": label, "payload": _make_payload(filters, limit)})

    if ctx["nsn"]:
        filters = dict(base)
        filters["keywords"] = [ctx["nsn"]]
        add_plan(f"nsn_only:{ctx['nsn']}", filters)

    if ctx.get("nsn_compact"):
        filters = dict(base)
        filters["keywords"] = [ctx["nsn_compact"]]
        add_plan(f"compact_nsn_only:{ctx['nsn_compact']}", filters)

    if ctx.get("niin"):
        filters = dict(base)
        filters["keywords"] = [ctx["niin"]]
        if ctx["fsc_code"]:
            filters["psc_codes"] = [ctx["fsc_code"]]
        add_plan(f"niin+psc:{ctx['niin']}" if ctx["fsc_code"] else f"niin_only:{ctx['niin']}", filters)

    for part_number in ctx.get("part_numbers", [])[:8]:
        filters = dict(base)
        filters["keywords"] = [part_number]
        if ctx["fsc_code"]:
            filters["psc_codes"] = [ctx["fsc_code"]]
        add_plan(f"part_number+psc:{part_number}" if ctx["fsc_code"] else f"part_number_only:{part_number}", filters)

    if ctx["fsc_code"]:
        filters = dict(base)
        filters["psc_codes"] = [ctx["fsc_code"]]
        if ctx["keywords"]:
            filters["keywords"] = ctx["keywords"][:4]
        add_plan(f"psc+keywords:{ctx['fsc_code']}", filters)

        filters = dict(base)
        filters["psc_codes"] = [ctx["fsc_code"]]
        filters["award_type_codes"] = ["B", "A"]
        if ctx["keywords"]:
            filters["keywords"] = ctx["keywords"][:4]
        add_plan(f"psc+po_priority:{ctx['fsc_code']}", filters)

    if ctx["naics_code"]:
        filters = dict(base)
        filters["naics_codes"] = [ctx["naics_code"]]
        if ctx["keywords"]:
            filters["keywords"] = ctx["keywords"][:4]
        add_plan(f"naics+keywords:{ctx['naics_code']}", filters)

    if ctx["keywords"]:
        filters = dict(base)
        filters["keywords"] = ctx["keywords"][:4]
        add_plan(f"keywords_first:{','.join(ctx['keywords'][:4])}", filters)

    for manufacturer in ctx.get("manufacturers", [])[:4]:
        kw = _phrase_to_keywords(manufacturer, max_terms=4)
        if not kw:
            continue
        filters = dict(base)
        filters["keywords"] = kw + ctx["keywords"][:2]
        if ctx["fsc_code"]:
            filters["psc_codes"] = [ctx["fsc_code"]]
        if ctx["naics_code"]:
            filters["naics_codes"] = [ctx["naics_code"]]
        add_plan(f"manufacturer+psc+keywords:{manufacturer}" if ctx["fsc_code"] else f"manufacturer+keywords:{manufacturer}", filters)

    for kw in ctx["keyword_variants"][:5]:
        filters = dict(base)
        filters["keywords"] = kw
        if ctx["fsc_code"]:
            filters["psc_codes"] = [ctx["fsc_code"]]
        if ctx["naics_code"]:
            filters["naics_codes"] = [ctx["naics_code"]]
        add_plan(f"psc+keywords_only:{ctx['fsc_code']}:{','.join(kw)}" if ctx["fsc_code"] else f"keywords_only:{','.join(kw)}", filters)

    for agency_name in ctx["agency_variants"][:2]:
        for kw in ctx["keyword_variants"][:3]:
            filters = dict(base)
            if ctx["fsc_code"]:
                filters["psc_codes"] = [ctx["fsc_code"]]
            if ctx["naics_code"]:
                filters["naics_codes"] = [ctx["naics_code"]]
            filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency_name}]
            filters["keywords"] = kw
            add_plan(f"agency+psc+keywords:{agency_name}:{','.join(kw)}" if ctx["fsc_code"] else f"agency+naics+keywords:{agency_name}:{','.join(kw)}", filters)

    for agency_name in ctx["agency_variants"][:2]:
        for kw in ctx["keyword_variants"][:3]:
            filters = dict(base)
            if ctx["fsc_code"]:
                filters["psc_codes"] = [ctx["fsc_code"]]
            filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency_name}]
            filters["keywords"] = kw
            add_plan(f"agency+psc_fallback:{agency_name}:{','.join(kw)}" if ctx["fsc_code"] else f"agency+keywords:{agency_name}:{','.join(kw)}", filters)

    deduped: list[dict[str, Any]] = []
    seen = set()
    for plan in plans:
        key = json.dumps(plan["payload"]["filters"], sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(plan)
    return deduped


def _call_usaspending(payload: dict[str, Any]) -> list[dict[str, Any]]:
    session = requests.Session()
    session.trust_env = False
    response = session.post(USASPENDING_SEARCH_URL, json=payload, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("results", []) or []


def _extract_candidate_fields(row: dict[str, Any]) -> dict[str, Any]:
    recipient = row.get("Recipient Name") or row.get("recipient_name") or row.get("Award Recipient") or row.get("award_recipient") or ""
    amount = row.get("Award Amount") or row.get("award_amount") or 0
    start_date = row.get("Start Date") or row.get("start_date") or ""
    awarding_agency = row.get("Awarding Agency") or row.get("awarding_agency") or ""
    award_id = row.get("Award ID") or row.get("award_id") or row.get("piid") or ""
    description = row.get("Description") or row.get("description") or ""
    return {
        "recipient_name": _safe(recipient),
        "award_amount": amount,
        "start_date": _safe(start_date),
        "awarding_agency": _safe(awarding_agency),
        "award_id": _safe(award_id),
        "description": _safe(description),
        "raw": row,
    }


def _combine_results(query_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    seen = set()
    for run in query_runs:
        label = run["label"]
        for row in run["rows"]:
            normalized = _extract_candidate_fields(row)
            key = (normalized["award_id"].lower(), normalized["recipient_name"].lower(), normalized["start_date"])
            if key in seen:
                continue
            seen.add(key)
            normalized["matched_by"] = label
            combined.append(normalized)
    return combined


def _has_any(text: str, terms: set[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _classification_boosts(row: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, list[str], list[str], bool, bool, bool]:
    description = (row.get("description") or "").lower()
    recipient = (row.get("recipient_name") or "").lower()
    matched_by = (row.get("matched_by") or "").lower()
    reasons: list[str] = []
    noise: list[str] = []
    score = 0.0

    product_terms_found = _has_any(description, PRODUCT_POSITIVE_TERMS)
    service_terms_found = _has_any(description, SERVICE_NOISE_TERMS)
    health_service_terms_found = _has_any(description, HEALTH_SERVICE_NOISE_TERMS)
    specific_6520_terms_found = _has_any(description, DLA_6520_PRODUCT_TERMS)
    strict_negative_terms_found = _has_any(description, STRICT_NEGATIVE_PRODUCT_TERMS)

    for term in product_terms_found:
        score += 2.0
        reasons.append(f"positive:{term}")

    for term in specific_6520_terms_found:
        score += 2.5
        reasons.append(f"6520_specific:{term}")

    for term in service_terms_found:
        score -= 2.5
        noise.append(term)

    for term in health_service_terms_found:
        score -= 3.0
        noise.append(term)

    for term in strict_negative_terms_found:
        score -= 4.0
        noise.append(f"strict_negative:{term}")

    nsn_hit = False
    if ctx.get("nsn") and ctx["nsn"].lower() in description:
        score += 6.0
        reasons.append("nsn_match")
        nsn_hit = True
    if ctx.get("nsn_compact") and ctx["nsn_compact"].lower() in description:
        score += 6.0
        reasons.append("compact_nsn_match")
        nsn_hit = True
    if ctx.get("niin") and ctx["niin"].lower() in description:
        score += 3.5
        reasons.append("niin_match")
        nsn_hit = True
    if matched_by.startswith("nsn_only:"):
        score += 4.0
        reasons.append("exact_nsn_query_match")
        nsn_hit = True
    if matched_by.startswith("compact_nsn_only:"):
        score += 4.0
        reasons.append("compact_nsn_query_match")
        nsn_hit = True
    if matched_by.startswith("niin"):
        score += 2.5
        reasons.append("niin_query_match")
        nsn_hit = True

    part_number_hit = False
    for pn in ctx.get("part_numbers", [])[:8]:
        if pn and pn.lower() in description:
            score += 4.0
            reasons.append(f"part_number_match:{pn}")
            part_number_hit = True
        if pn and matched_by.endswith(pn.lower()):
            score += 3.0
            reasons.append(f"part_number_query_match:{pn}")
            part_number_hit = True

    manufacturer_hit = False
    approved_source_hit = False

    for m in ctx.get("manufacturers", [])[:8]:
        ml = m.lower()
        if ml and (ml in recipient or ml in description):
            score += 4.0
            reasons.append(f"manufacturer_match:{m}")
            manufacturer_hit = True

    for m in ctx.get("catalog_manufacturers", [])[:8]:
        ml = m.lower()
        if ml and (ml in recipient or ml in description):
            score += 4.5
            reasons.append(f"catalog_manufacturer_match:{m}")
            manufacturer_hit = True

    for m in ctx.get("approved_source_names", [])[:10]:
        ml = m.lower()
        if ml and (ml in recipient or ml in description):
            score += 5.0
            reasons.append(f"approved_source_match:{m}")
            manufacturer_hit = True
            approved_source_hit = True

    if ctx.get("catalog_reference_count"):
        for pn in ctx.get("catalog_part_numbers", [])[:8]:
            if pn and (pn.lower() in description or matched_by.endswith(pn.lower())):
                score += 2.5
                reasons.append(f"catalog_part_number_evidence:{pn}")
                part_number_hit = True

    if ctx.get("fsc_code") == "6520":
        if "dental" in description or "oral" in description:
            score += 2.0
            reasons.append("dental_or_oral_match")
        if "paste" in description:
            score += 2.0
            reasons.append("paste_match")

    for token in ctx.get("keywords", [])[:8]:
        if token and token.lower() in description:
            score += 0.5
            reasons.append(f"context_keyword:{token}")

    vendor_blocked = any(term in recipient for term in SEED_BLOCK_VENDOR_TERMS)
    if vendor_blocked:
        score -= 4.0
        noise.append("blocked_vendor_entity_pattern")

    has_product_evidence = bool(product_terms_found) or bool(specific_6520_terms_found) or manufacturer_hit or nsn_hit or part_number_hit or "paste_match" in reasons or "dental_or_oral_match" in reasons

    seedable = has_product_evidence and not vendor_blocked and (
        approved_source_hit
        or manufacturer_hit
        or nsn_hit
        or part_number_hit
        or bool(specific_6520_terms_found)
    )

    strict_seedable = (
        not vendor_blocked
        and not strict_negative_terms_found
        and (
            approved_source_hit
            or manufacturer_hit
            or nsn_hit
            or part_number_hit
            or bool(specific_6520_terms_found)
        )
    )

    return score, reasons, noise, has_product_evidence, seedable, strict_seedable


def _classify_award(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    score, reasons, noise_flags, has_product_evidence, seedable, strict_seedable = _classification_boosts(row, ctx)

    category = "product_like"
    if score <= -1.5:
        category = "excluded_noise"
    elif score < 3.0 or not has_product_evidence:
        category = "service_like"

    return {
        **row,
        "relevance_score": round(score, 2),
        "relevance_reasons": _dedupe_keep_order(reasons),
        "noise_flags": _dedupe_keep_order(noise_flags),
        "match_category": category,
        "seedable_product_evidence": seedable,
        "strict_seedable_product_evidence": strict_seedable,
    }


def _split_awards(normalized_awards: list[dict[str, Any]], ctx: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    classified = [_classify_award(row, ctx) for row in normalized_awards]
    product_like = [x for x in classified if x["match_category"] == "product_like"]
    service_like = [x for x in classified if x["match_category"] == "service_like"]
    excluded_noise = [x for x in classified if x["match_category"] == "excluded_noise"]
    seedable_product_like = [x for x in product_like if x.get("seedable_product_evidence")]
    strict_seedable_product_like = [x for x in product_like if x.get("strict_seedable_product_evidence")]

    product_like.sort(key=lambda x: (-x["relevance_score"], x["recipient_name"]))
    service_like.sort(key=lambda x: (-x["relevance_score"], x["recipient_name"]))
    excluded_noise.sort(key=lambda x: (x["relevance_score"], x["recipient_name"]))
    seedable_product_like.sort(key=lambda x: (-x["relevance_score"], x["recipient_name"]))
    strict_seedable_product_like.sort(key=lambda x: (-x["relevance_score"], x["recipient_name"]))

    return {
        "product_like": product_like,
        "service_like": service_like,
        "excluded_noise": excluded_noise,
        "seedable_product_like": seedable_product_like,
        "strict_seedable_product_like": strict_seedable_product_like,
    }


def _rank_vendors(awards: list[dict[str, Any]], ctx: dict[str, Any], strict: bool = False) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "vendor": "",
            "award_count": 0,
            "total_award_amount": 0.0,
            "last_award_date": "",
            "agencies": set(),
            "sample_awards": [],
            "score": 0.0,
            "match_reasons": [],
            "max_relevance_score": 0.0,
            "seedable_vendor": False,
            "strict_seedable_vendor": False,
            "evidence": [],
        }
    )

    for row in awards:
        name = row["recipient_name"]
        if not name:
            continue
        g = grouped[name]
        g["vendor"] = name
        g["award_count"] += 1
        try:
            g["total_award_amount"] += float(row["award_amount"] or 0)
        except Exception:
            pass
        if row["start_date"] and (not g["last_award_date"] or row["start_date"] > g["last_award_date"]):
            g["last_award_date"] = row["start_date"]
        if row["awarding_agency"]:
            g["agencies"].add(row["awarding_agency"])
        g["max_relevance_score"] = max(g["max_relevance_score"], float(row.get("relevance_score", 0)))
        g["seedable_vendor"] = g["seedable_vendor"] or bool(row.get("seedable_product_evidence"))
        g["strict_seedable_vendor"] = g["strict_seedable_vendor"] or bool(row.get("strict_seedable_product_evidence"))
        if len(g["sample_awards"]) < 5:
            g["sample_awards"].append({
                "award_id": row["award_id"],
                "start_date": row["start_date"],
                "award_amount": row["award_amount"],
                "awarding_agency": row["awarding_agency"],
                "description": row["description"],
                "matched_by": row.get("matched_by", ""),
                "relevance_score": row.get("relevance_score", 0),
                "match_category": row.get("match_category", ""),
                "seedable_product_evidence": row.get("seedable_product_evidence", False),
                "strict_seedable_product_evidence": row.get("strict_seedable_product_evidence", False),
                "relevance_reasons": row.get("relevance_reasons", []),
            })
        for reason in row.get("relevance_reasons", [])[:6]:
            if reason not in g["evidence"]:
                g["evidence"].append(reason)

    ranked: list[dict[str, Any]] = []
    approved_name_set = {x.lower() for x in ctx.get("approved_source_names", [])}
    manufacturer_set = {x.lower() for x in ctx.get("manufacturers", [])}

    for _, g in grouped.items():
        score = 0.0
        reasons: list[str] = []
        agency_list = sorted(g["agencies"])

        score += min(4.0, g["award_count"] * 0.75)
        if g["award_count"]:
            reasons.append(f"award_count={g['award_count']}")

        if ctx["agency_variants"]:
            agency_lowers = {a.lower() for a in agency_list}
            if any(av.lower() in agency_lowers for av in ctx["agency_variants"]):
                score += 2.0
                reasons.append("same_agency_or_alias")

        if ctx["fsc_code"]:
            score += 1.0
            reasons.append(f"fsc_context={ctx['fsc_code']}")

        vendor_lower = g["vendor"].lower()
        if any(x in vendor_lower for x in approved_name_set if x):
            score += 5.0
            reasons.append("vendor_matches_approved_source")
        if any(x in vendor_lower for x in manufacturer_set if x):
            score += 4.0
            reasons.append("vendor_matches_manufacturer")

        if strict and g["strict_seedable_vendor"]:
            score += 3.0
            reasons.append("strict_seedable_vendor_gate_passed")
        elif (not strict) and g["seedable_vendor"]:
            score += 2.0
            reasons.append("seedable_vendor_gate_passed")

        score += min(6.0, g["max_relevance_score"])
        reasons.append(f"max_relevance={g['max_relevance_score']}")

        if g["last_award_date"]:
            reasons.append(f"last_award={g['last_award_date']}")

        g["score"] = round(score, 2)
        g["match_reasons"] = reasons
        g["why_matched"] = _dedupe_keep_order(
            reasons + g["evidence"][:6] + [
                f"sample_awards={len(g['sample_awards'])}",
                f"agencies={', '.join(agency_list[:2])}" if agency_list else "",
            ]
        )[:8]
        g["agencies"] = agency_list
        ranked.append(g)

    ranked.sort(key=lambda x: (-x["score"], -x["max_relevance_score"], -x["award_count"], -x["total_award_amount"], x["vendor"]))
    return ranked[:25]


def _approved_source_vendor_candidates(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    vendors: list[dict[str, Any]] = []
    source_rows = (ctx.get("approved_sources") or [])[:10]
    solicitation_rows = (ctx.get("solicitation_rows") or [])[:3]
    for source in source_rows:
        company_name = _safe(source.get("company_name"))
        cage = _safe(source.get("cage"))
        if not company_name:
            continue
        why = _dedupe_keep_order(
            [
                "approved_source_seed",
                f"cage={cage}" if cage else "",
                f"nsn={ctx.get('nsn')}" if ctx.get("nsn") else "",
                f"fsc_context={ctx.get('fsc_code')}" if ctx.get("fsc_code") else "",
                f"solicitation={ctx.get('solicitation_number')}" if ctx.get("solicitation_number") else "",
            ]
        )
        sample_awards = []
        for row in solicitation_rows:
            sample_awards.append(
                {
                    "award_id": row.get("solicitation_number") or row.get("pr_number") or "",
                    "start_date": row.get("issue_date") or "",
                    "award_amount": None,
                    "awarding_agency": ctx.get("agency") or "",
                    "description": f"Approved source context for {ctx.get('nomenclature') or ctx.get('title') or 'item'}",
                    "matched_by": "approved_source",
                    "relevance_score": 10.0,
                    "match_category": "approved_source",
                    "seedable_product_evidence": True,
                    "strict_seedable_product_evidence": True,
                    "relevance_reasons": ["approved_source_seed"],
                }
            )
        vendors.append(
            {
                "vendor": company_name,
                "cage": cage,
                "award_count": 0,
                "total_award_amount": 0.0,
                "last_award_date": "",
                "agencies": [ctx.get("agency")] if ctx.get("agency") else [],
                "sample_awards": sample_awards,
                "score": 12.0,
                "match_reasons": ["approved_source_seed", "approved_source_vendor_gate_passed"],
                "max_relevance_score": 10.0,
                "seedable_vendor": True,
                "strict_seedable_vendor": True,
                "evidence": ["approved_source_seed"],
                "why_matched": why,
                "source_type": "DIBBS_APPROVED_SOURCE",
            }
        )
    return vendors


def _merge_vendor_lists(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + secondary:
        vendor_name = _safe(item.get("vendor")).lower()
        if not vendor_name or vendor_name in seen:
            continue
        seen.add(vendor_name)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _search_usaspending_with_context(
    ctx: dict[str, Any],
    *,
    opportunity_id: int | None,
    research_profile: dict[str, Any],
    limit: int = 50,
) -> dict[str, Any]:
    plans = _query_plan(ctx, limit=limit)

    query_runs: list[dict[str, Any]] = []
    first_hit_index: int | None = None

    for idx, plan in enumerate(plans):
        rows = _call_usaspending(plan["payload"])
        query_runs.append({
            "label": plan["label"],
            "rows": rows,
            "count": len(rows),
            "payload": plan["payload"],
        })
        if rows and first_hit_index is None:
            first_hit_index = idx
        if sum(len(run["rows"]) for run in query_runs) >= limit:
            break
        if first_hit_index is not None and idx >= first_hit_index + 2:
            break

    combined = _combine_results(query_runs)
    buckets = _split_awards(combined, ctx)
    ranked_product = _rank_vendors(buckets["product_like"], ctx, strict=False)
    ranked_seedable = _rank_vendors(buckets["seedable_product_like"], ctx, strict=False)
    ranked_strict = _rank_vendors(buckets["strict_seedable_product_like"], ctx, strict=True)
    ranked_service = _rank_vendors(buckets["service_like"], ctx, strict=False)
    approved_source_vendors = _approved_source_vendor_candidates(ctx)
    likely_vendors = _merge_vendor_lists(approved_source_vendors, ranked_strict)
    seedable_vendors = _merge_vendor_lists(approved_source_vendors, ranked_seedable)
    product_like_vendors = _merge_vendor_lists(approved_source_vendors, ranked_product)
    first_nonzero_run = next((run for run in query_runs if run["count"] > 0), None)
    nsn_direct_hit = any(run["label"].startswith("nsn_only:") and run["count"] > 0 for run in query_runs)
    history_match_source = "nsn_direct" if nsn_direct_hit else ("fallback" if first_nonzero_run else "none")
    history_match_label = (
        "NSN direct match"
        if history_match_source == "nsn_direct"
        else "Keyword / fallback match"
        if history_match_source == "fallback"
        else "No USAspending history match"
    )

    return {
        "opportunity_id": opportunity_id,
        "research_profile": research_profile,
        "context": ctx,
        "history_match_source": history_match_source,
        "history_match_label": history_match_label,
        "history_match_query_label": first_nonzero_run["label"] if first_nonzero_run else None,
        "awards_found": len(combined),
        "awards": combined[:20],
        "product_like_awards": buckets["product_like"][:20],
        "seedable_product_like_awards": buckets["seedable_product_like"][:20],
        "strict_seedable_product_like_awards": buckets["strict_seedable_product_like"][:20],
        "service_like_awards": buckets["service_like"][:20],
        "excluded_noise": buckets["excluded_noise"][:20],
        "approved_source_vendors": approved_source_vendors,
        "likely_vendors": likely_vendors,
        "product_like_vendors": product_like_vendors,
        "seedable_product_like_vendors": seedable_vendors,
        "strict_seedable_product_like_vendors": ranked_strict,
        "service_like_vendors": ranked_service,
        "query_debug": [
            {
                "label": run["label"],
                "count": run["count"],
                "filters": run["payload"].get("filters", {}),
                "limit": run["payload"].get("limit"),
            }
            for run in query_runs
        ],
    }


def search_usaspending_for_opportunity(opp: Opportunity, db: Session | None = None, limit: int = 50) -> dict[str, Any]:
    ctx = _opp_context(opp, db=db)
    research_profile = build_research_profile(opp, getattr(opp, "parsed_json", None) if isinstance(getattr(opp, "parsed_json", None), dict) else None)
    return _search_usaspending_with_context(ctx, opportunity_id=opp.id, research_profile=research_profile, limit=limit)


def search_usaspending_for_nsn(db: Session, nsn: str, limit: int = 50) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {
            "opportunity_id": None,
            "research_profile": {},
            "context": {"nsn": nsn},
            "history_match_source": "none",
            "history_match_label": "Invalid NSN",
            "history_match_query_label": None,
            "awards_found": 0,
            "awards": [],
            "product_like_awards": [],
            "seedable_product_like_awards": [],
            "strict_seedable_product_like_awards": [],
            "service_like_awards": [],
            "excluded_noise": [],
            "approved_source_vendors": [],
            "likely_vendors": [],
            "product_like_vendors": [],
            "seedable_product_like_vendors": [],
            "strict_seedable_product_like_vendors": [],
            "service_like_vendors": [],
            "query_debug": [],
            "error": "NSN must contain exactly 13 digits.",
        }
    ctx = {
        "title": "",
        "agency": "DLA",
        "agency_variants": _agency_variants("DLA"),
        "naics_code": "",
        "fsc_code": target.fsc,
        "solicitation_number": "",
        "nsn": target.nsn,
        "keywords": [target.fsc],
        "keyword_variants": [[target.nsn], [target.compact], [target.niin]],
        "nomenclature": "",
        "manufacturers": [],
        "part_numbers": [],
        "approved_sources": [],
        "solicitation_rows": [],
        "approved_source_names": [],
        "approved_source_cages": [],
    }
    ctx = _expand_context_with_catalog(ctx, _catalog_context_for_nsn(db, target.nsn))
    research_profile = {
        "source": "nsn_catalog",
        "nsn": target.nsn,
        "fsc": target.fsc,
        "niin": target.niin,
        "nomenclature": ctx.get("nomenclature") or ctx.get("catalog_item_name") or "",
        "keywords": ctx.get("keywords") or [],
    }
    return _search_usaspending_with_context(ctx, opportunity_id=None, research_profile=research_profile, limit=limit)


def seed_usaspending_vendors_into_leads(
    db: Session,
    opp: Opportunity,
    research_result: dict[str, Any],
    limit: int = 15,
    seed_mode: str = "product_only",
) -> dict[str, Any]:
    created = 0
    updated = 0
    seeded: list[dict[str, Any]] = []
    ctx = research_result.get("context", {})
    provider_repo = ProviderRepository(db, organization_id=getattr(opp, "organization_id", None))
    nsn = ctx.get("nsn") or None
    fsc = ctx.get("fsc_code") or None
    nomenclature = ctx.get("nomenclature") or ctx.get("title") or None

    if seed_mode == "strict":
        candidates = research_result.get("strict_seedable_product_like_vendors", [])
    elif seed_mode == "all":
        candidates = research_result.get("seedable_product_like_vendors", []) + research_result.get("service_like_vendors", [])
    else:
        candidates = research_result.get("seedable_product_like_vendors", [])

    candidates = candidates[:limit]

    for item in candidates:
        company_name = _safe(item.get("vendor"))
        if not company_name:
            continue

        existing = (
            db.query(VendorLead)
            .filter(
                VendorLead.opportunity_id == opp.id,
                VendorLead.company_name == company_name,
                VendorLead.source_type == "USASPENDING_AWARD_HISTORY",
            )
            .first()
        )

        notes = (
            f"USAspending candidate ({seed_mode}). "
            f"Award count: {item.get('award_count', 0)}. "
            f"Total award amount: {item.get('total_award_amount', 0)}. "
            f"Last award: {_safe(item.get('last_award_date'))}. "
            f"Reasons: {', '.join(item.get('match_reasons', []))}. "
            f"Sample awards: {' | '.join(f'{award.get('award_id')}: {award.get('description')}' for award in (item.get('sample_awards') or [])[:3])}"
        )
        raw_text = (
            f"Derived from USAspending research for solicitation {_safe(ctx.get('solicitation_number'))}; "
            f"title={_safe(ctx.get('title'))}; nomenclature={_safe(ctx.get('nomenclature'))}; "
            f"agency={_safe(ctx.get('agency'))}; keywords={', '.join(ctx.get('keywords', []))}; "
            f"fsc={_safe(ctx.get('fsc_code'))}; nsn={_safe(ctx.get('nsn'))}; "
            f"manufacturers={', '.join(ctx.get('manufacturers', []))}; "
            f"part_numbers={', '.join(ctx.get('part_numbers', []))}; seed_mode={seed_mode}; "
            f"query_debug={json.dumps(research_result.get('query_debug', [])[:3])}"
        )
        confidence = min(95, 55 + int(float(item.get("score", 0)) * 5))

        if existing:
            if existing.organization_id is None and getattr(opp, "organization_id", None) is not None:
                existing.organization_id = getattr(opp, "organization_id", None)
            existing.notes = notes
            existing.raw_text = raw_text
            existing.confidence = confidence
            existing.is_approved_source = False
            existing.status = existing.status or "NEW"
            updated += 1
        else:
            rec = VendorLead(
                organization_id=getattr(opp, "organization_id", None),
                opportunity_id=opp.id,
                source_type="USASPENDING_AWARD_HISTORY",
                company_name=company_name,
                cage=None,
                part_number=None,
                nsn=ctx.get("nsn") or None,
                status="NEW",
                confidence=confidence,
                is_approved_source=False,
                raw_text=raw_text,
                notes=notes,
            )
            db.add(rec)
            created += 1

        sample_awards = item.get("sample_awards") or []
        sample_award = sample_awards[0] if sample_awards else {}
        provider_notes = (
            f"USAspending awardee. Award count: {item.get('award_count', 0)}. "
            f"Total award amount: {item.get('total_award_amount', 0)}. "
            f"Last award: {_safe(item.get('last_award_date'))}. "
            f"Sample award: {_safe(sample_award.get('award_id'))}."
        )
        try:
            provider_repo.create(
                ProviderCreate(
                    company_name=company_name,
                    notes=provider_notes,
                    item=ProviderItemCreate(
                        nsn=nsn,
                        fsc=fsc,
                        nomenclature=nomenclature,
                        relationship_type="Awardee",
                        source="USAspending",
                        source_url=_safe(sample_award.get("award_id")),
                        confidence=90,
                        notes=provider_notes,
                    ),
                )
            )
        except Exception:
            db.rollback()

        try:
            amount = float(item.get("total_award_amount") or 0) or None
        except Exception:
            amount = None
        if amount:
            sample_awards = item.get("sample_awards") or []
            sample_award = sample_awards[0] if sample_awards else {}
            existing_price = (
                db.query(PriceHistory)
                .filter(
                    PriceHistory.opportunity_id == opp.id,
                    PriceHistory.award_id == _safe(sample_award.get("award_id")),
                    PriceHistory.supplier_name == company_name,
                    PriceHistory.source_label == "USAspending",
                )
                .first()
            )
            if not existing_price:
                db.add(
                    PriceHistory(
                        organization_id=getattr(opp, "organization_id", None),
                        opportunity_id=opp.id,
                        nsn=ctx.get("nsn") or None,
                        award_id=_safe(sample_award.get("award_id")),
                        award_date=_safe(sample_award.get("start_date")) or _safe(item.get("last_award_date")),
                        supplier_name=company_name,
                        cage=item.get("cage"),
                        total_price=amount,
                        source_label="USAspending",
                        confidence=80,
                        raw_text=_safe(sample_award.get("description")),
                    )
                )

        seeded.append({
            "company_name": company_name,
            "award_count": item.get("award_count", 0),
            "score": item.get("score", 0),
            "last_award_date": item.get("last_award_date", ""),
            "sample_awards": item.get("sample_awards", [])[:3],
        })

    db.commit()

    return {
        "opportunity_id": opp.id,
        "seed_mode": seed_mode,
        "created": created,
        "updated": updated,
        "seeded_count": len(seeded),
        "seeded": seeded,
        "query_debug": research_result.get("query_debug", []),
    }
