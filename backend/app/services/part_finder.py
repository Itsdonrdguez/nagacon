from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.opportunity import Opportunity
from app.models.provider import Provider, ProviderItem
from app.services.intelligence.wbparts_service import get_wbparts_reference
from app.services.nsn_catalog.catalog_service import get_nsn_catalog_summary
from app.services.nsn_catalog.normalizer import compact_nsn, normalize_nsn


def find_part_for_opportunity(
    db: Session,
    opportunity_id: int,
    *,
    organization_id: int | None = None,
    force_wbparts_refresh: bool = False,
) -> dict[str, Any]:
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if organization_id is not None:
        query = query.filter(Opportunity.organization_id == organization_id)
    opp = query.first()
    if not opp:
        return {"status": "not_found", "error": "Opportunity not found", "opportunity_id": opportunity_id}

    target = _target_from_opportunity(opp)
    if not target.get("nsn"):
        return {
            "status": "missing_nsn",
            "opportunity": _opportunity_payload(opp),
            "part": target,
            "confidence": {"identity": "low", "supplier": "low", "award_history": "low"},
            "next_actions": ["Extract or enter the NSN before running part intelligence."],
        }
    return build_part_finder_result(
        db,
        target,
        opportunity=opp,
        organization_id=organization_id,
        force_wbparts_refresh=force_wbparts_refresh,
    )


def find_part_for_nsn(
    db: Session,
    nsn: str,
    *,
    organization_id: int | None = None,
) -> dict[str, Any]:
    target = _target_from_nsn(nsn)
    if not target.get("nsn"):
        return {"status": "invalid_nsn", "error": "NSN must contain exactly 13 digits.", "input": nsn}
    return build_part_finder_result(db, target, organization_id=organization_id)


def find_parts_batch(
    db: Session,
    *,
    opportunity_ids: list[int] | None = None,
    nsns: list[str] | None = None,
    organization_id: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for opportunity_id in (opportunity_ids or [])[:limit]:
        items.append(find_part_for_opportunity(db, int(opportunity_id), organization_id=organization_id))
    for nsn in (nsns or [])[:limit]:
        items.append(find_part_for_nsn(db, str(nsn), organization_id=organization_id))
    return {
        "status": "ok",
        "requested": {"opportunity_ids": opportunity_ids or [], "nsns": nsns or []},
        "count": len(items),
        "items": items,
    }


def build_part_finder_result(
    db: Session,
    target: dict[str, Any],
    *,
    opportunity: Opportunity | None = None,
    organization_id: int | None = None,
    force_wbparts_refresh: bool = False,
) -> dict[str, Any]:
    catalog = get_nsn_catalog_summary(db, target["nsn"])
    identity = catalog.get("identity") or {}
    references = catalog.get("references") or []
    cage_profiles = catalog.get("cage_profiles") or []
    catalog_providers = catalog.get("providers") or []
    recommendations = catalog.get("vendor_recommendations") or []
    award_history = catalog.get("award_history") or {}
    nsn_awards = catalog.get("nsn_award_evidence") or {}
    wbparts = get_wbparts_reference(
        db,
        target["nsn"],
        opportunity_id=getattr(opportunity, "id", None),
        force_refresh=force_wbparts_refresh,
    )
    wbparts_cross_references = wbparts.get("cross_references") or []
    wbparts_alternates = wbparts.get("part_alternates") or []
    wbparts_related_products = wbparts.get("related_products") or []

    part_numbers = _unique_part_numbers(
        [row.get("part_number") for row in references]
        + [row.get("part_number") for row in wbparts_cross_references]
        + wbparts_alternates,
        nsn=target["nsn"],
    )
    cages = _unique([row.get("cage") for row in references] + [row.get("cage") for row in cage_profiles] + [row.get("cage") for row in wbparts_cross_references])
    manufacturers = _unique(
        [row.get("company_name") for row in references]
        + [row.get("company_name") for row in cage_profiles]
        + [(row.get("official_profile") or {}).get("company") for row in cage_profiles]
        + [row.get("manufacturer") for row in wbparts_cross_references]
    )
    providers = _provider_candidates(
        db,
        target["nsn"],
        catalog_providers,
        recommendations,
        wbparts_cross_references,
        organization_id=organization_id,
    )
    awardees = _awardee_candidates(db, target["nsn"], award_history, nsn_awards, opportunity_id=getattr(opportunity, "id", None))

    item_name = (
        target.get("nomenclature")
        or identity.get("item_name")
        or _first([row.get("nomenclature") for row in catalog_providers])
        or wbparts.get("item_name")
    )
    confidence = _confidence(
        has_identity=bool(identity.get("item_name") or target.get("nomenclature") or wbparts.get("item_name")),
        references_count=len(references),
        provider_count=len(providers),
        award_count=len(awardees),
        wbparts_cross_reference_count=len(wbparts_cross_references),
    )

    return {
        "status": "ok",
        "opportunity": _opportunity_payload(opportunity) if opportunity else None,
        "part": {
            **target,
            "item_name": item_name,
            "part_numbers": part_numbers,
            "cages": cages,
            "manufacturers": manufacturers,
            "reference_count": len(references),
            "related_nsns": wbparts_related_products[:10],
        },
        "providers": providers,
        "awardees": awardees,
        "wbparts": {
            "status": wbparts.get("status"),
            "source_url": wbparts.get("source_url"),
            "fetched_at": wbparts.get("fetched_at"),
            "cache_hit": bool(wbparts.get("cache_hit")),
            "item_name": wbparts.get("item_name"),
            "part_alternates": wbparts_alternates[:20],
            "cross_references": wbparts_cross_references[:20],
            "related_products": wbparts_related_products[:20],
            "demand_history": (wbparts.get("demand_history") or [])[:20],
            "summary": wbparts.get("summary") or {},
        },
        "evidence": {
            "catalog_status": catalog.get("status"),
            "identity": identity,
            "reference_count": len(references),
            "cage_profile_count": len(cage_profiles),
            "provider_count": len(providers),
            "award_history_count": award_history.get("count", 0),
            "nsn_award_evidence_count": nsn_awards.get("count", 0),
            "source_freshness": catalog.get("source_freshness"),
            "wbparts": {
                "status": wbparts.get("status"),
                "cross_reference_count": len(wbparts_cross_references),
                "alternate_count": len(wbparts_alternates),
                "related_product_count": len(wbparts_related_products),
                "source_url": wbparts.get("source_url"),
            },
        },
        "confidence": confidence,
        "next_actions": _next_actions(target, references, providers, awardees, catalog, wbparts),
    }


def _target_from_nsn(value: str) -> dict[str, Any]:
    parsed = normalize_nsn(value)
    if not parsed:
        return {"input": value, "nsn": None}
    return {
        "input": value,
        "nsn": parsed.nsn,
        "compact_nsn": parsed.compact,
        "fsc": parsed.fsc,
        "niin": parsed.niin,
        "quantity": None,
        "quantity_display": None,
        "nomenclature": None,
        "source": "nsn",
    }


def _target_from_opportunity(opp: Opportunity) -> dict[str, Any]:
    payload = getattr(opp, "raw_payload", None) if isinstance(getattr(opp, "raw_payload", None), dict) else {}
    search_row = payload.get("dibbs_search_row") if isinstance(payload.get("dibbs_search_row"), dict) else {}
    item_signals = payload.get("item_signals") if isinstance(payload.get("item_signals"), dict) else {}
    detail = payload.get("dibbs_detail") if isinstance(payload.get("dibbs_detail"), dict) else {}
    structured = detail.get("structured") if isinstance(detail.get("structured"), dict) else detail
    solicitation_row = _selected_solicitation_row(structured, getattr(opp, "source_opportunity_id", None), getattr(opp, "solicitation_number", None))

    raw_nsn = (
        search_row.get("nsn")
        or item_signals.get("nsn")
        or detail.get("nsn")
        or getattr(opp, "solicitation_number", None)
        or getattr(opp, "source_opportunity_id", None)
        or getattr(opp, "title", None)
    )
    parsed = normalize_nsn(raw_nsn)
    quantity = _clean_quantity(search_row.get("quantity") or solicitation_row.get("qty") or solicitation_row.get("quantity"))
    nomenclature = _clean(search_row.get("nomenclature") or detail.get("nomenclature") or getattr(opp, "title", None), 300)
    if not parsed:
        return {
            "input": raw_nsn,
            "nsn": None,
            "quantity": quantity,
            "quantity_display": f"Qty: {quantity}" if quantity else None,
            "nomenclature": nomenclature,
            "source": "opportunity",
        }
    return {
        "input": raw_nsn,
        "nsn": parsed.nsn,
        "compact_nsn": parsed.compact,
        "fsc": parsed.fsc,
        "niin": parsed.niin,
        "quantity": quantity,
        "quantity_display": f"Qty: {quantity}" if quantity else None,
        "nomenclature": nomenclature,
        "pr_number": search_row.get("pr_number") or solicitation_row.get("pr_number"),
        "source": "opportunity",
    }


def _selected_solicitation_row(structured: dict[str, Any], *values: str | None) -> dict[str, Any]:
    rows = structured.get("solicitations") if isinstance(structured, dict) else []
    if not isinstance(rows, list):
        return {}
    needles = {_compact(value) for value in values if _compact(value)}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_key = _compact(row.get("solicitation_number"))
        if row_key and row_key in needles:
            return row
    return rows[0] if rows and isinstance(rows[0], dict) else {}


def _provider_candidates(
    db: Session,
    nsn: str,
    catalog_providers: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    wbparts_cross_references: list[dict[str, Any]],
    *,
    organization_id: int | None,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(name: str | None, cage: str | None, role: str | None, source: str | None, confidence: Any = None, provider_id: int | None = None):
        clean_name = _clean(name, 300) or (f"CAGE {cage}" if cage else "Unknown Provider")
        clean_cage = _clean(cage, 20).upper() or None
        key = clean_cage or clean_name.lower()
        item = candidates.setdefault(
            key,
            {
                "provider_id": provider_id,
                "name": clean_name,
                "cage": clean_cage,
                "roles": [],
                "sources": [],
                "confidence": confidence,
            },
        )
        if provider_id and not item.get("provider_id"):
            item["provider_id"] = provider_id
        if role and role not in item["roles"]:
            item["roles"].append(role)
        if source and source not in item["sources"]:
            item["sources"].append(source)
        if confidence is not None and item.get("confidence") is None:
            item["confidence"] = confidence

    query = db.query(Provider, ProviderItem).join(ProviderItem, ProviderItem.provider_id == Provider.id).filter(ProviderItem.nsn == nsn)
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    for provider, item in query.limit(100).all():
        add_candidate(provider.canonical_name or provider.company_name, provider.cage, item.relationship_type, item.source, item.confidence, provider.id)

    for row in catalog_providers:
        add_candidate(row.get("company_name"), row.get("cage"), row.get("relationship_type"), row.get("source"), row.get("confidence"), row.get("provider_id"))

    for row in recommendations:
        roles = row.get("roles") or []
        for role in roles or ["Recommended Supplier"]:
            add_candidate(row.get("company_name"), row.get("cage"), role, "NSN Recommendation", row.get("score") or row.get("confidence"), row.get("provider_id"))

    for row in wbparts_cross_references:
        add_candidate(
            row.get("manufacturer"),
            row.get("cage"),
            row.get("relationship_type") or "Cross Reference",
            "WBParts",
            row.get("confidence"),
            None,
        )

    return sorted(candidates.values(), key=lambda item: (-(len(item["roles"])), item["name"]))[:25]


def _awardee_candidates(
    db: Session,
    nsn: str,
    award_history: dict[str, Any],
    nsn_awards: dict[str, Any],
    *,
    opportunity_id: int | None = None,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def add(name: str | None, cage: str | None, amount: Any = None, source: str | None = None, date: str | None = None, confidence: str | None = None):
        clean_name = _clean(name, 300) or (f"CAGE {cage}" if cage else "Unknown Awardee")
        clean_cage = _clean(cage, 20).upper() or None
        key = clean_cage or clean_name.lower()
        item = rows.setdefault(
            key,
            {
                "name": clean_name,
                "cage": clean_cage,
                "award_count": 0,
                "total_award_amount": 0.0,
                "latest_award_date": None,
                "sources": [],
                "best_confidence": confidence,
            },
        )
        item["award_count"] += 1
        numeric = _float(amount)
        if numeric:
            item["total_award_amount"] += numeric
        if date and (not item["latest_award_date"] or str(date) > str(item["latest_award_date"])):
            item["latest_award_date"] = date
        if source and source not in item["sources"]:
            item["sources"].append(source)
        if confidence and not item.get("best_confidence"):
            item["best_confidence"] = confidence

    for row in award_history.get("items") or []:
        add(row.get("recipient_name"), row.get("recipient_cage"), row.get("award_amount"), row.get("source_system"), row.get("award_date"), row.get("match_confidence"))

    for row in nsn_awards.get("items") or []:
        add(row.get("recipient_name"), row.get("recipient_cage"), row.get("award_amount"), row.get("source_system"), row.get("award_date"), row.get("match_confidence"))

    query = db.query(AwardHistory).filter(AwardHistory.nsn == nsn)
    if opportunity_id is not None:
        query = query.union(db.query(AwardHistory).filter(AwardHistory.opportunity_id == opportunity_id))
    for row in query.limit(100).all():
        add(row.recipient_name, row.recipient_cage, row.award_amount, row.source_system, row.award_date, row.match_confidence)

    output = list(rows.values())
    for item in output:
        item["total_award_amount"] = round(item["total_award_amount"], 2)
    return sorted(output, key=lambda item: (-item["award_count"], -item["total_award_amount"], item["name"]))[:25]


def _opportunity_payload(opp: Opportunity | None) -> dict[str, Any] | None:
    if not opp:
        return None
    return {
        "id": opp.id,
        "source": opp.source,
        "solicitation_number": opp.solicitation_number,
        "source_opportunity_id": opp.source_opportunity_id,
        "title": opp.title,
        "agency": opp.agency,
        "due_at": opp.due_at.isoformat() if getattr(opp, "due_at", None) else None,
    }


def _confidence(*, has_identity: bool, references_count: int, provider_count: int, award_count: int, wbparts_cross_reference_count: int = 0) -> dict[str, Any]:
    identity_score = 30 + (45 if has_identity else 0) + min(references_count * 4, 25)
    supplier_score = min(provider_count * 12 + references_count * 2 + min(wbparts_cross_reference_count * 3, 12), 100)
    award_score = min(award_count * 15, 100)
    return {
        "identity_score": min(identity_score, 100),
        "supplier_score": supplier_score,
        "award_history_score": award_score,
        "identity": _label(identity_score),
        "supplier": _label(supplier_score),
        "award_history": _label(award_score),
    }


def _next_actions(
    target: dict[str, Any],
    references: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    awardees: list[dict[str, Any]],
    catalog: dict[str, Any],
    wbparts: dict[str, Any] | None = None,
) -> list[str]:
    actions: list[str] = []
    if not target.get("quantity"):
        actions.append("Confirm solicitation quantity from DIBBS detail or PDF.")
    if not references:
        actions.append("Import PUB LOG references for this NSN to find CAGEs and part numbers.")
    if not providers:
        actions.append("Seed provider candidates from catalog references or approved-source PDFs.")
    if not awardees:
        actions.append("Run USAspending/SAM award history search to find prior awardees.")
    if wbparts and wbparts.get("status") == "ok" and (wbparts.get("cross_references") or []):
        actions.append("Review WBParts cross references as supplemental manufacturer and alternate-part evidence.")
    if wbparts and wbparts.get("status") == "not_found":
        actions.append("WBParts did not return an NSN page. Lean on PUB LOG, parsed solicitation evidence, and provider history instead.")
    if catalog.get("confidence", {}).get("identity") == "low":
        actions.append("Review item identity manually before outreach.")
    if not actions:
        actions.append("Use provider candidates for quote outreach and verify availability, lead time, and compliance.")
    return actions


def _unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _unique_part_numbers(values: list[Any], *, nsn: str | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    blocked = {
        compact_nsn(nsn),
        str(nsn or "").strip().upper(),
    }
    for value in values:
        text = _clean(value)
        if not text:
            continue
        compact = compact_nsn(text)
        if compact and compact in blocked:
            continue
        key = re.sub(r"[^0-9A-Z]+", "", text.upper())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first(values: list[Any]) -> str | None:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return None


def _clean(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_len] if max_len and text else text


def _clean_quantity(value: Any) -> str | None:
    text = _clean(value)
    return text.replace(",", "") if text else None


def _compact(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _label(score: float | int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"
