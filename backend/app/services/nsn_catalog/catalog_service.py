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
        "award_history": awards,
        "nsn_award_evidence": nsn_awards,
        "pricing": pricing,
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
