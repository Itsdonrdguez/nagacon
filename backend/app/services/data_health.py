from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.nsn_catalog import (
    NsnAwardEvidence,
    NsnCatalogImportRun,
    NsnEvidence,
    NsnIntelligenceSnapshot,
    NsnInterchangeability,
    NsnMaster,
    NsnReference,
)
from app.models.opportunity import Opportunity
from app.models.provider import Provider, ProviderItem
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact
from app.services.saas_readiness import build_org_scope_audit
from app.services.source_freshness import build_source_freshness


def _scope_org(query, model, organization_id: int | None):
    if organization_id is None or not hasattr(model, "organization_id"):
        return query
    return query.filter(or_(model.organization_id == organization_id, model.organization_id.is_(None)))


def _count(db: Session, model, organization_id: int | None = None) -> int:
    query = db.query(func.count(getattr(model, "id")))
    query = _scope_org(query, model, organization_id)
    return int(query.scalar() or 0)


def _count_filtered(db: Session, model, filters, organization_id: int | None = None) -> int:
    query = db.query(func.count(getattr(model, "id")))
    query = _scope_org(query, model, organization_id)
    for filter_clause in filters:
        query = query.filter(filter_clause)
    return int(query.scalar() or 0)


def _count_provider_items(db: Session, organization_id: int | None = None) -> int:
    query = db.query(func.count(ProviderItem.id))
    if organization_id is not None:
        query = query.join(Provider, Provider.id == ProviderItem.provider_id).filter(
            or_(Provider.organization_id == organization_id, Provider.organization_id.is_(None))
        )
    return int(query.scalar() or 0)


def _count_providers_with_items(db: Session, organization_id: int | None = None) -> int:
    query = db.query(func.count(func.distinct(ProviderItem.provider_id)))
    if organization_id is not None:
        query = query.join(Provider, Provider.id == ProviderItem.provider_id).filter(
            or_(Provider.organization_id == organization_id, Provider.organization_id.is_(None))
        )
    return int(query.scalar() or 0)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 2)


def _status(count: int, thin_threshold: int = 1) -> str:
    if count <= 0:
        return "missing"
    if count < thin_threshold:
        return "thin"
    return "ready"


def _catalog_status(latest_publog: dict[str, Any] | None, nsn_count: int, reference_count: int) -> str:
    if not latest_publog or nsn_count <= 0:
        return "missing"
    if latest_publog.get("status") != "completed" or nsn_count < 1000 or reference_count <= 0:
        return "thin"
    return "ready"


def _vendor_status(provider_count: int, provider_item_coverage: float, leads_per_opportunity: float) -> str:
    if provider_count <= 0:
        return "missing"
    if provider_count < 25 or provider_item_coverage < 0.5 or leads_per_opportunity < 0.05:
        return "thin"
    return "ready"


def _award_status(award_history_count: int, nsn_award_evidence_count: int) -> str:
    if award_history_count <= 0 and nsn_award_evidence_count <= 0:
        return "missing"
    if nsn_award_evidence_count <= 0:
        return "thin"
    return "ready"


def _workflow_status(opportunity_count: int, part_finder_artifacts: int) -> str:
    if opportunity_count <= 0:
        return "missing"
    if part_finder_artifacts <= 0:
        return "thin"
    return "ready"


def _latest_publog_run(db: Session) -> dict[str, Any] | None:
    run = db.query(NsnCatalogImportRun).order_by(NsnCatalogImportRun.completed_at.desc().nullslast()).first()
    if not run:
        return None
    return {
        "id": run.id,
        "source_name": run.source_name,
        "source_version": run.source_version,
        "source_file": run.source_file,
        "status": run.status,
        "rows_seen": run.rows_seen or 0,
        "rows_imported": run.rows_imported or 0,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _coverage_status(value: float, missing_when_zero: bool = True) -> str:
    if value <= 0 and missing_when_zero:
        return "missing"
    if value < 0.5:
        return "thin"
    return "ready"


def build_data_health(db: Session, organization_id: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.utcnow()

    counts = {
        "opportunities": _count(db, Opportunity, organization_id),
        "nsn_master": _count(db, NsnMaster),
        "nsn_references": _count(db, NsnReference),
        "nsn_interchangeability": _count(db, NsnInterchangeability),
        "nsn_evidence": _count(db, NsnEvidence),
        "nsn_award_evidence": _count(db, NsnAwardEvidence),
        "nsn_snapshots": _count(db, NsnIntelligenceSnapshot),
        "providers": _count(db, Provider, organization_id),
        "provider_items": _count_provider_items(db, organization_id),
        "vendor_leads": _count(db, VendorLead, organization_id),
        "vendor_quotes": _count(db, VendorQuote, organization_id),
        "award_history": _count(db, AwardHistory, organization_id),
        "workspace_artifacts": _count(db, WorkspaceArtifact, organization_id),
        "search_jobs": _count(db, SearchJob, organization_id),
    }

    providers_with_items = _count_providers_with_items(db, organization_id)
    quotes_requested = _count_filtered(
        db,
        VendorQuote,
        [VendorQuote.status.in_(["REQUESTED", "SENT", "FOLLOWED_UP"])],
        organization_id,
    )
    quotes_received = _count_filtered(db, VendorQuote, [VendorQuote.status == "RECEIVED"], organization_id)
    part_finder_artifacts = _count_filtered(
        db,
        WorkspaceArtifact,
        [WorkspaceArtifact.artifact_type == "PART_FINDER"],
        organization_id,
    )

    coverage = {
        "references_per_nsn": _ratio(counts["nsn_references"], counts["nsn_master"]),
        "interchangeability_per_nsn": _ratio(counts["nsn_interchangeability"], counts["nsn_master"]),
        "award_evidence_per_nsn": _ratio(counts["nsn_award_evidence"], counts["nsn_master"]),
        "provider_item_coverage": _ratio(providers_with_items, counts["providers"]),
        "vendor_leads_per_opportunity": _ratio(counts["vendor_leads"], counts["opportunities"]),
        "quotes_requested": quotes_requested,
        "quotes_received": quotes_received,
        "part_finder_artifacts": part_finder_artifacts,
    }

    latest_publog = _latest_publog_run(db)
    categories = [
        {
            "key": "nsn_catalog",
            "label": "NSN Catalog",
            "status": _catalog_status(latest_publog, counts["nsn_master"], counts["nsn_references"]),
            "summary": "PUB LOG base item records, references, interchangeability, and evidence.",
            "metrics": [
                {"label": "NSNs", "value": counts["nsn_master"]},
                {"label": "References", "value": counts["nsn_references"]},
                {"label": "Interchangeability", "value": counts["nsn_interchangeability"]},
                {"label": "Evidence", "value": counts["nsn_evidence"]},
            ],
        },
        {
            "key": "vendor_intelligence",
            "label": "Vendor Intelligence",
            "status": _vendor_status(
                counts["providers"],
                coverage["provider_item_coverage"],
                coverage["vendor_leads_per_opportunity"],
            ),
            "summary": "Providers, CAGE-linked items, leads, quotes, and awardee evidence.",
            "metrics": [
                {"label": "Providers", "value": counts["providers"]},
                {"label": "Provider Items", "value": counts["provider_items"]},
                {"label": "Vendor Leads", "value": counts["vendor_leads"]},
                {"label": "Vendor Quotes", "value": counts["vendor_quotes"]},
            ],
        },
        {
            "key": "award_history",
            "label": "Award History",
            "status": _award_status(counts["award_history"], counts["nsn_award_evidence"]),
            "summary": "USAspending and closed-solicitation award evidence used for vendor discovery.",
            "metrics": [
                {"label": "Opportunity Awards", "value": counts["award_history"]},
                {"label": "NSN Award Evidence", "value": counts["nsn_award_evidence"]},
                {"label": "Snapshots", "value": counts["nsn_snapshots"]},
            ],
        },
        {
            "key": "workflow",
            "label": "Workflow Automation",
            "status": _workflow_status(counts["opportunities"], part_finder_artifacts),
            "summary": "Opportunities, workspace artifacts, Part Finder runs, and background jobs.",
            "metrics": [
                {"label": "Opportunities", "value": counts["opportunities"]},
                {"label": "Workspace Artifacts", "value": counts["workspace_artifacts"]},
                {"label": "Part Finder Runs", "value": part_finder_artifacts},
                {"label": "Search Jobs", "value": counts["search_jobs"]},
            ],
        },
    ]

    readiness_checks = [
        {
            "key": "publog_imported",
            "label": "PUB LOG import",
            "status": _catalog_status(latest_publog, counts["nsn_master"], counts["nsn_references"]),
            "detail": "NSN master records are required for the free NSN-NOW-style backbone.",
        },
        {
            "key": "reference_graph",
            "label": "Reference graph",
            "status": _coverage_status(coverage["references_per_nsn"]),
            "detail": "Part numbers and CAGE relationships make supplier matching much stronger.",
        },
        {
            "key": "provider_items",
            "label": "Provider item coverage",
            "status": _coverage_status(coverage["provider_item_coverage"]),
            "detail": "Provider item links are needed to turn providers into sourcing leads.",
        },
        {
            "key": "award_evidence",
            "label": "Award evidence",
            "status": _award_status(counts["award_history"], counts["nsn_award_evidence"]),
            "detail": "Award records are the bridge from closed solicitations to vendor history.",
        },
        {
            "key": "part_finder",
            "label": "Part Finder automation",
            "status": "ready" if part_finder_artifacts > 0 else "missing",
            "detail": "Part Finder artifacts show the system is building sourcing intelligence from opportunities.",
        },
    ]

    source_freshness = build_source_freshness(db, organization_id=organization_id, now=current_time)
    saas_readiness = build_org_scope_audit(db, organization_id=organization_id)

    summary = {
        "ready": sum(1 for item in categories + readiness_checks if item["status"] == "ready"),
        "thin": sum(1 for item in categories + readiness_checks if item["status"] == "thin"),
        "missing": sum(1 for item in categories + readiness_checks if item["status"] == "missing"),
        "fresh_sources": source_freshness.get("summary", {}).get("fresh", 0),
        "stale_sources": source_freshness.get("summary", {}).get("stale", 0),
        "missing_sources": source_freshness.get("summary", {}).get("missing", 0),
        "saas_ready": saas_readiness.get("summary", {}).get("ready_for_saas", False),
    }

    return {
        "organization_id": organization_id,
        "generated_at": current_time.isoformat(),
        "summary": summary,
        "counts": counts,
        "coverage": coverage,
        "categories": categories,
        "readiness_checks": readiness_checks,
        "latest_publog_import": latest_publog,
        "source_freshness": source_freshness,
        "saas_readiness": saas_readiness,
    }
