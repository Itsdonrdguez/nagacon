from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead
from app.services.workspace_service import ensure_parsed

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
    nomenclature = _preferred_nomenclature(parsed, title)
    keywords = _build_exact_item_terms(parsed, nomenclature or title, fsc)
    if not keywords:
        keywords = _tokenize_keywords(f"{title} {raw_text}", limit=10)

    manufacturers = _dedupe_keep_order([_safe(x) for x in (parsed.get("manufacturers") or [])])
    part_numbers = _dedupe_keep_order([_safe(x) for x in (parsed.get("part_numbers") or []) if _safe(x)])
    approved_sources = parsed.get("approved_sources") or []

    return {
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
        "approved_source_names": _dedupe_keep_order([_safe(x.get("company_name")) for x in approved_sources if _safe(x.get("company_name"))]),
        "approved_source_cages": _dedupe_keep_order([_safe(x.get("cage")) for x in approved_sources if _safe(x.get("cage"))]),
    }


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

    if ctx["nsn"]:
        filters = dict(base)
        filters["keywords"] = [ctx["nsn"]]
        plans.append({"label": f"nsn_only:{ctx['nsn']}", "payload": _make_payload(filters, limit)})

    for manufacturer in ctx.get("manufacturers", [])[:4]:
        kw = _phrase_to_keywords(manufacturer, max_terms=4)
        if not kw:
            continue
        filters = dict(base)
        filters["keywords"] = kw + ctx["keywords"][:2]
        plans.append({"label": f"manufacturer+keywords:{manufacturer}", "payload": _make_payload(filters, limit)})

    for agency_name in ctx["agency_variants"][:3]:
        for kw in ctx["keyword_variants"][:3]:
            filters = dict(base)
            if ctx["naics_code"]:
                filters["naics_codes"] = [ctx["naics_code"]]
            filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency_name}]
            filters["keywords"] = kw
            plans.append({"label": f"agency+naics+keywords:{agency_name}:{','.join(kw)}", "payload": _make_payload(filters, limit)})

    for agency_name in ctx["agency_variants"][:3]:
        for kw in ctx["keyword_variants"][:4]:
            filters = dict(base)
            filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency_name}]
            filters["keywords"] = kw
            plans.append({"label": f"agency+keywords:{agency_name}:{','.join(kw)}", "payload": _make_payload(filters, limit)})

    for kw in ctx["keyword_variants"][:5]:
        filters = dict(base)
        filters["keywords"] = kw
        if ctx["naics_code"]:
            filters["naics_codes"] = [ctx["naics_code"]]
        plans.append({"label": f"keywords_only:{','.join(kw)}", "payload": _make_payload(filters, limit)})

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
    response = requests.post(USASPENDING_SEARCH_URL, json=payload, timeout=HTTP_TIMEOUT)
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

    part_number_hit = False
    for pn in ctx.get("part_numbers", [])[:8]:
        if pn and pn.lower() in description:
            score += 4.0
            reasons.append(f"part_number_match:{pn}")
            part_number_hit = True

    manufacturer_hit = False
    approved_source_hit = False

    for m in ctx.get("manufacturers", [])[:8]:
        ml = m.lower()
        if ml and (ml in recipient or ml in description):
            score += 4.0
            reasons.append(f"manufacturer_match:{m}")
            manufacturer_hit = True

    for m in ctx.get("approved_source_names", [])[:10]:
        ml = m.lower()
        if ml and (ml in recipient or ml in description):
            score += 5.0
            reasons.append(f"approved_source_match:{m}")
            manufacturer_hit = True
            approved_source_hit = True

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
            })

    ranked: list[dict[str, Any]] = []
    approved_name_set = {x.lower() for x in ctx.get("approved_source_names", [])}
    manufacturer_set = {x.lower() for x in ctx.get("manufacturers", [])}

    for _, g in grouped.items():
        score = 0.0
        reasons: list[str] = []

        score += min(4.0, g["award_count"] * 0.75)
        if g["award_count"]:
            reasons.append(f"award_count={g['award_count']}")

        if ctx["agency_variants"]:
            agency_lowers = {a.lower() for a in g["agencies"]}
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
        g["agencies"] = sorted(g["agencies"])
        ranked.append(g)

    ranked.sort(key=lambda x: (-x["score"], -x["max_relevance_score"], -x["award_count"], -x["total_award_amount"], x["vendor"]))
    return ranked[:25]


def search_usaspending_for_opportunity(opp: Opportunity, db: Session | None = None, limit: int = 50) -> dict[str, Any]:
    ctx = _opp_context(opp, db=db)
    plans = _query_plan(ctx, limit=limit)

    query_runs: list[dict[str, Any]] = []
    first_hit_index: int | None = None

    for idx, plan in enumerate(plans):
        rows = _call_usaspending(plan["payload"])
        query_runs.append({"label": plan["label"], "rows": rows, "count": len(rows)})
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

    return {
        "opportunity_id": opp.id,
        "context": ctx,
        "awards_found": len(combined),
        "awards": combined[:20],
        "product_like_awards": buckets["product_like"][:20],
        "seedable_product_like_awards": buckets["seedable_product_like"][:20],
        "strict_seedable_product_like_awards": buckets["strict_seedable_product_like"][:20],
        "service_like_awards": buckets["service_like"][:20],
        "excluded_noise": buckets["excluded_noise"][:20],
        "likely_vendors": ranked_strict,
        "product_like_vendors": ranked_product,
        "seedable_product_like_vendors": ranked_seedable,
        "strict_seedable_product_like_vendors": ranked_strict,
        "service_like_vendors": ranked_service,
        "query_debug": [{"label": run["label"], "count": run["count"]} for run in query_runs],
    }


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
            f"Reasons: {', '.join(item.get('match_reasons', []))}"
        )
        raw_text = (
            f"Derived from USAspending research for solicitation {_safe(ctx.get('solicitation_number'))}; "
            f"title={_safe(ctx.get('title'))}; nomenclature={_safe(ctx.get('nomenclature'))}; "
            f"agency={_safe(ctx.get('agency'))}; keywords={', '.join(ctx.get('keywords', []))}; "
            f"fsc={_safe(ctx.get('fsc_code'))}; nsn={_safe(ctx.get('nsn'))}; "
            f"manufacturers={', '.join(ctx.get('manufacturers', []))}; "
            f"part_numbers={', '.join(ctx.get('part_numbers', []))}; seed_mode={seed_mode}"
        )
        confidence = min(95, 55 + int(float(item.get("score", 0)) * 5))

        if existing:
            existing.notes = notes
            existing.raw_text = raw_text
            existing.confidence = confidence
            existing.is_approved_source = False
            existing.status = existing.status or "NEW"
            updated += 1
        else:
            rec = VendorLead(
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

        seeded.append({
            "company_name": company_name,
            "award_count": item.get("award_count", 0),
            "score": item.get("score", 0),
            "last_award_date": item.get("last_award_date", ""),
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
