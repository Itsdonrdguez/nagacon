from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnIntelligenceSnapshot
from app.services.nsn_catalog.award_evidence import persist_nsn_award_evidence
from app.services.nsn_catalog.catalog_service import get_nsn_catalog_summary
from app.services.nsn_catalog.normalizer import normalize_nsn
from app.services.nsn_catalog.provider_seeding import seed_providers_from_nsn_catalog
from app.services.research.usaspending_research_service import search_usaspending_for_nsn


def refresh_nsn_intelligence(
    db: Session,
    nsn: str,
    *,
    run_usaspending: bool = True,
    seed_providers: bool = False,
    limit: int = 50,
    organization_id: int | None = None,
) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {
            "status": "invalid_nsn",
            "error": "NSN must contain exactly 13 digits.",
        }

    usaspending = None
    provider_seed = None
    if run_usaspending:
        usaspending = search_usaspending_for_nsn(db, target.nsn, limit=limit)
        award_persistence = persist_nsn_award_evidence(db, target.nsn, usaspending)
    else:
        award_persistence = None
    if seed_providers:
        provider_seed = seed_providers_from_nsn_catalog(
            db,
            target.nsn,
            organization_id=organization_id,
            limit=limit,
        )

    catalog_summary = get_nsn_catalog_summary(db, target.nsn)
    snapshot_payload = {
        "target": catalog_summary.get("target"),
        "identity": catalog_summary.get("identity"),
        "references": catalog_summary.get("references", [])[:50],
        "interchangeability": catalog_summary.get("interchangeability", [])[:50],
        "vendor_recommendations": catalog_summary.get("vendor_recommendations", [])[:25],
        "providers": catalog_summary.get("providers", [])[:25],
        "award_history": catalog_summary.get("award_history"),
        "nsn_award_evidence": catalog_summary.get("nsn_award_evidence"),
        "pricing": catalog_summary.get("pricing"),
        "confidence": catalog_summary.get("confidence"),
        "next_actions": catalog_summary.get("next_actions"),
        "usaspending": _trim_usaspending(usaspending) if usaspending else None,
        "award_persistence": award_persistence,
        "provider_seed": provider_seed,
    }
    confidence = {
        "catalog_identity": (catalog_summary.get("confidence") or {}).get("identity"),
        "vendor_recommendations": bool(catalog_summary.get("vendor_recommendations")),
        "usaspending_awards_found": (usaspending or {}).get("awards_found", 0) if usaspending else 0,
        "nsn_awards_created": (award_persistence or {}).get("created", 0) if award_persistence else 0,
        "nsn_awards_updated": (award_persistence or {}).get("updated", 0) if award_persistence else 0,
        "history_match_source": (usaspending or {}).get("history_match_source") if usaspending else None,
    }
    snapshot = NsnIntelligenceSnapshot(
        nsn=target.nsn,
        compact_nsn=target.compact,
        source_scope="refresh",
        summary_json=snapshot_payload,
        confidence_json=confidence,
        generated_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return {
        "status": "ok",
        "snapshot_id": snapshot.id,
        "nsn": target.nsn,
        "compact_nsn": target.compact,
        "run_usaspending": run_usaspending,
        "seed_providers": seed_providers,
        "summary": snapshot_payload,
        "confidence": confidence,
    }


def _trim_usaspending(usaspending: dict[str, Any] | None) -> dict[str, Any] | None:
    if not usaspending:
        return None
    return {
        "history_match_source": usaspending.get("history_match_source"),
        "history_match_label": usaspending.get("history_match_label"),
        "history_match_query_label": usaspending.get("history_match_query_label"),
        "awards_found": usaspending.get("awards_found", 0),
        "awards": (usaspending.get("awards") or [])[:20],
        "product_like_awards": (usaspending.get("product_like_awards") or [])[:20],
        "seedable_product_like_awards": (usaspending.get("seedable_product_like_awards") or [])[:20],
        "strict_seedable_product_like_awards": (usaspending.get("strict_seedable_product_like_awards") or [])[:20],
        "likely_vendors": (usaspending.get("likely_vendors") or [])[:20],
        "seedable_product_like_vendors": (usaspending.get("seedable_product_like_vendors") or [])[:20],
        "query_debug": (usaspending.get("query_debug") or [])[:20],
    }
