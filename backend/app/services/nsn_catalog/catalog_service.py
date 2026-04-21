from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.nsn_catalog import (
    NsnEvidence,
    NsnIntelligenceSnapshot,
    NsnInterchangeability,
    NsnMaster,
    NsnReference,
)
from app.models.price_history import PriceHistory
from app.models.provider import Provider, ProviderItem
from app.services.nsn_catalog.award_evidence import summarize_nsn_award_evidence
from app.services.nsn_catalog.normalizer import NormalizedNsn, normalize_nsn
from app.services.nsn_catalog.vendor_recommendations import build_vendor_recommendations


def _model_dict(row: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(row, field, None) for field in fields}


def _confidence_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def get_nsn_catalog_summary(db: Session, value: str) -> dict[str, Any]:
    target = normalize_nsn(value)
    if not target:
        return {
            "status": "invalid_nsn",
            "input": value,
            "message": "NSN must contain exactly 13 digits.",
        }

    master = (
        db.query(NsnMaster)
        .filter(NsnMaster.compact_nsn == target.compact)
        .first()
    )
    references = (
        db.query(NsnReference)
        .filter(NsnReference.compact_nsn == target.compact)
        .order_by(NsnReference.confidence.desc().nullslast(), NsnReference.cage.asc().nullslast(), NsnReference.part_number.asc().nullslast())
        .limit(100)
        .all()
    )
    interchangeability = (
        db.query(NsnInterchangeability)
        .filter(NsnInterchangeability.compact_nsn == target.compact)
        .order_by(NsnInterchangeability.confidence.desc().nullslast(), NsnInterchangeability.related_nsn.asc())
        .limit(100)
        .all()
    )
    evidence = (
        db.query(NsnEvidence)
        .filter(NsnEvidence.compact_nsn == target.compact)
        .order_by(NsnEvidence.confidence.desc().nullslast(), NsnEvidence.created_at.desc())
        .limit(100)
        .all()
    )
    snapshot = (
        db.query(NsnIntelligenceSnapshot)
        .filter(NsnIntelligenceSnapshot.compact_nsn == target.compact)
        .order_by(NsnIntelligenceSnapshot.generated_at.desc().nullslast(), NsnIntelligenceSnapshot.created_at.desc())
        .first()
    )

    providers = _provider_rows(db, target)
    vendor_recommendations = build_vendor_recommendations(db, target.nsn, limit=25)
    awards = _award_summary(db, target)
    nsn_awards = summarize_nsn_award_evidence(db, target.nsn)
    pricing = _price_summary(db, target)
    identity_confidence = _identity_confidence(master, references)
    related_masters = _related_master_map(db, interchangeability)
    alternate_graph = _alternate_graph(target, references, interchangeability, evidence, providers, vendor_recommendations, related_masters)

    return {
        "status": "ok",
        "target": {
            "nsn": target.nsn,
            "compact_nsn": target.compact,
            "fsc": target.fsc,
            "niin": target.niin,
        },
        "identity": _identity_payload(master, target),
        "references": [
            _model_dict(row, [
                "cage",
                "company_name",
                "part_number",
                "reference_type",
                "relationship_type",
                "source_name",
                "source_version",
                "confidence",
            ])
            for row in references
        ],
        "interchangeability": [
            _model_dict(row, [
                "related_nsn",
                "relationship_type",
                "order_of_use",
                "source_name",
                "source_version",
                "confidence",
                "notes",
            ])
            for row in interchangeability
        ],
        "providers": providers,
        "vendor_recommendations": vendor_recommendations,
        "cage_profiles": _cage_profiles(references, evidence),
        "award_history": awards,
        "nsn_award_evidence": nsn_awards,
        "pricing": pricing,
        "alternate_graph": alternate_graph,
        "source_freshness": _source_freshness(master, references, evidence, snapshot),
        "evidence": [
            _model_dict(row, [
                "claim_type",
                "claim_value",
                "source_name",
                "source_url",
                "source_version",
                "matched_by",
                "confidence",
                "evidence_text",
            ])
            for row in evidence
        ],
        "confidence": {
            "identity_score": identity_confidence,
            "identity": _confidence_label(identity_confidence),
            "has_catalog_record": bool(master),
            "has_reference_records": bool(references),
            "has_award_history": awards["count"] > 0,
            "has_provider_matches": bool(providers),
            "has_vendor_recommendations": bool(vendor_recommendations),
        },
        "snapshot": snapshot.summary_json if snapshot else None,
        "next_actions": _next_actions(master, references, providers, awards),
    }


def _source_freshness(
    master: NsnMaster | None,
    references: list[NsnReference],
    evidence: list[NsnEvidence],
    snapshot: NsnIntelligenceSnapshot | None,
) -> dict[str, Any]:
    publog_versions = sorted(
        {
            value
            for value in [getattr(master, "source_version", None), *[getattr(row, "source_version", None) for row in references]]
            if value
        }
    )
    latest_catalog_at = max(
        [value for value in [getattr(master, "updated_at", None), *[getattr(row, "updated_at", None) for row in references]] if value],
        default=None,
    )
    latest_evidence_at = max([getattr(row, "updated_at", None) for row in evidence if getattr(row, "updated_at", None)], default=None)
    return {
        "publog_source_version": publog_versions[-1] if publog_versions else None,
        "catalog_updated_at": latest_catalog_at.isoformat() if latest_catalog_at else None,
        "evidence_updated_at": latest_evidence_at.isoformat() if latest_evidence_at else None,
        "latest_snapshot_generated_at": snapshot.generated_at.isoformat() if snapshot and snapshot.generated_at else None,
        "source_labels": {
            "catalog": "official_publog",
            "awards": "usaspending_api",
            "providers": "organization_scoped",
        },
    }


def _cage_profiles(references: list[NsnReference], evidence: list[NsnEvidence]) -> list[dict[str, Any]]:
    by_cage: dict[str, dict[str, Any]] = {}
    for row in references:
        cage = (row.cage or "").strip()
        if not cage:
            continue
        profile = by_cage.setdefault(
            cage,
            {
                "cage": cage,
                "company_name": row.company_name,
                "part_numbers": [],
                "source": row.source_name,
                "source_version": row.source_version,
                "confidence": row.confidence,
                "official_profile": None,
            },
        )
        if row.company_name and not profile.get("company_name"):
            profile["company_name"] = row.company_name
        if row.part_number and row.part_number not in profile["part_numbers"]:
            profile["part_numbers"].append(row.part_number)
    for row in evidence:
        if row.claim_type != "cage_profile" or not row.claim_value:
            continue
        profile = by_cage.setdefault(
            row.claim_value,
            {
                "cage": row.claim_value,
                "company_name": None,
                "part_numbers": [],
                "source": row.source_name,
                "source_version": row.source_version,
                "confidence": row.confidence,
                "official_profile": None,
            },
        )
        payload = row.raw_payload or {}
        profile["official_profile"] = {
            "company": payload.get("COMPANY"),
            "status": payload.get("CAGE_STATUS"),
            "type": payload.get("TYPE"),
            "city": payload.get("CITY"),
            "state": payload.get("STATE_PROVINCE"),
            "country": payload.get("COUNTRY"),
            "zip": payload.get("ZIP_POSTAL_ZONE"),
            "cao": payload.get("CAO"),
            "source": row.source_name,
        }
        profile["company_name"] = profile.get("company_name") or payload.get("COMPANY")
    return sorted(by_cage.values(), key=lambda item: item.get("cage") or "")


def _identity_payload(master: NsnMaster | None, target: NormalizedNsn) -> dict[str, Any]:
    if not master:
        return {
            "nsn": target.nsn,
            "compact_nsn": target.compact,
            "fsc": target.fsc,
            "niin": target.niin,
            "item_name": None,
            "status": "not_in_local_catalog",
        }
    return _model_dict(master, [
        "nsn",
        "compact_nsn",
        "fsc",
        "niin",
        "item_name",
        "item_name_code",
        "demil_code",
        "criticality_code",
        "public_data_status",
        "source_name",
        "source_version",
    ]) | {"status": "catalog_match"}


def _identity_confidence(master: NsnMaster | None, references: list[NsnReference]) -> float:
    score = 0.15
    if master:
        score += 0.55
        if master.item_name:
            score += 0.1
        if master.source_name and master.source_name.lower() != "manual":
            score += 0.1
    if references:
        score += min(0.1, len(references) * 0.02)
    return min(score, 1.0)


def _provider_rows(db: Session, target: NormalizedNsn) -> list[dict[str, Any]]:
    rows = (
        db.query(Provider, ProviderItem)
        .join(ProviderItem, ProviderItem.provider_id == Provider.id)
        .filter(ProviderItem.nsn == target.nsn)
        .order_by(ProviderItem.confidence.desc().nullslast(), Provider.company_name.asc())
        .limit(50)
        .all()
    )
    return [
        {
            "provider_id": provider.id,
            "company_name": provider.company_name,
            "cage": provider.cage,
            "uei": provider.uei,
            "website": provider.website,
            "relationship_type": item.relationship_type,
            "source": item.source,
            "source_url": item.source_url,
            "confidence": item.confidence,
            "notes": item.notes,
        }
        for provider, item in rows
    ]


def _award_summary(db: Session, target: NormalizedNsn) -> dict[str, Any]:
    rows = (
        db.query(AwardHistory)
        .filter(AwardHistory.nsn == target.nsn)
        .order_by(AwardHistory.match_score.desc().nullslast(), AwardHistory.award_date.desc().nullslast())
        .limit(50)
        .all()
    )
    amounts = [row.award_amount for row in rows if row.award_amount is not None]
    return {
        "count": len(rows),
        "amount_low": min(amounts) if amounts else None,
        "amount_high": max(amounts) if amounts else None,
        "amount_average": round(sum(amounts) / len(amounts), 2) if amounts else None,
        "top_recipients": _top_counts([row.recipient_name for row in rows]),
        "items": [
            _model_dict(row, [
                "source_system",
                "award_id",
                "piid",
                "recipient_name",
                "recipient_cage",
                "award_date",
                "award_amount",
                "awarding_agency",
                "description",
                "match_score",
                "match_confidence",
                "match_reasons",
            ])
            for row in rows[:20]
        ],
    }


def _price_summary(db: Session, target: NormalizedNsn) -> dict[str, Any]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.nsn == target.nsn)
        .order_by(PriceHistory.confidence.desc().nullslast(), PriceHistory.award_date.desc().nullslast())
        .limit(50)
        .all()
    )
    prices = [row.unit_price for row in rows if row.unit_price is not None]
    return {
        "count": len(rows),
        "unit_low": min(prices) if prices else None,
        "unit_high": max(prices) if prices else None,
        "unit_average": round(sum(prices) / len(prices), 2) if prices else None,
        "items": [
            _model_dict(row, [
                "award_id",
                "award_date",
                "supplier_name",
                "cage",
                "quantity",
                "total_price",
                "unit_price",
                "source_label",
                "confidence",
            ])
            for row in rows[:20]
        ],
    }


def _top_counts(values: list[str | None], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        key = (value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _next_actions(
    master: NsnMaster | None,
    references: list[NsnReference],
    providers: list[dict[str, Any]],
    awards: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if not master:
        actions.append("Import or refresh PUB LOG catalog data for this NSN.")
    if not references:
        actions.append("Load MCRD/reference data to identify CAGE and part-number relationships.")
    if not providers:
        actions.append("Seed provider candidates from catalog references, DIBBS PDFs, or award history.")
    if awards.get("count", 0) == 0:
        actions.append("Run USAspending award research with NSN, NIIN, part-number, and item-name fallbacks.")
    if not actions:
        actions.append("Review evidence and confidence before using the vendor shortlist for bid outreach.")
    return actions


def _alternate_graph(
    target: NormalizedNsn,
    references: list[NsnReference],
    interchangeability: list[NsnInterchangeability],
    evidence: list[NsnEvidence],
    providers: list[dict[str, Any]],
    vendor_recommendations: list[dict[str, Any]],
    related_masters: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    part_numbers = []
    cages = []
    related_nodes = []
    for row in references:
        if row.part_number:
            part_numbers.append({
                "part_number": row.part_number,
                "cage": row.cage,
                "company_name": row.company_name,
                "source": row.source_name,
                "relationship_type": row.relationship_type,
            })
        if row.cage:
            cages.append({
                "cage": row.cage,
                "company_name": row.company_name,
                "source": row.source_name,
            })
    for row in interchangeability:
        related_master = related_masters.get(row.related_compact_nsn or "", {})
        related_nodes.append({
            "node_type": "nsn" if not str(row.related_nsn or "").startswith("INC-") else "related_inc",
            "related_value": row.related_nsn,
            "related_compact": row.related_compact_nsn,
            "related_item_name": related_master.get("item_name") or row.notes,
            "related_fsc": related_master.get("fsc"),
            "relationship_type": row.relationship_type,
            "notes": row.notes,
            "source": row.source_name,
            "confidence": row.confidence,
        })
    for row in evidence:
        if row.claim_type == "related_item_concept":
            related_nodes.append({
                "node_type": "related_item_concept",
                "related_value": row.claim_value,
                "related_compact": None,
                "relationship_type": "related_item_concept",
                "notes": row.evidence_text,
                "source": row.source_name,
                "confidence": row.confidence,
            })
    return {
        "root_nsn": target.nsn,
        "part_numbers": _dedupe_dicts(part_numbers, ["part_number", "cage", "source"]),
        "cages": _dedupe_dicts(cages, ["cage", "source"]),
        "related_nodes": _dedupe_dicts(related_nodes, ["related_value", "relationship_type", "source"]),
        "actual_related_nsn_count": len([row for row in related_nodes if row.get("node_type") == "nsn"]),
        "concept_only_count": len([row for row in related_nodes if row.get("node_type") != "nsn"]),
        "provider_count": len(providers),
        "vendor_candidate_count": len(vendor_recommendations),
    }


def _dedupe_dicts(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        token = "|".join(str(row.get(key) or "") for key in keys)
        if token in seen:
            continue
        seen.add(token)
        out.append(row)
    return out


def _related_master_map(db: Session, interchangeability: list[NsnInterchangeability]) -> dict[str, dict[str, Any]]:
    related_compacts = sorted(
        {
            row.related_compact_nsn
            for row in interchangeability
            if row.related_compact_nsn and len(str(row.related_compact_nsn)) == 13
        }
    )
    if not related_compacts:
        return {}
    rows = (
        db.query(NsnMaster)
        .filter(NsnMaster.compact_nsn.in_(related_compacts))
        .all()
    )
    return {
        row.compact_nsn: {
            "nsn": row.nsn,
            "compact_nsn": row.compact_nsn,
            "item_name": row.item_name,
            "fsc": row.fsc,
        }
        for row in rows
    }
