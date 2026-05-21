from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.import_run import ImportRun
from app.models.nsn_catalog import NsnCatalogImportRun, NsnIntelligenceSnapshot
from app.models.opportunity import Opportunity
from app.models.provider import Provider
from app.models.search_job import SearchJob
from app.utils.utc import utcnow


def _age_days(value: datetime | None, now: datetime) -> int | None:
    if not value:
        return None
    return max((now.date() - value.date()).days, 0)


def _status(age_days: int | None, stale_after_days: int) -> str:
    if age_days is None:
        return "missing"
    if age_days > stale_after_days:
        return "stale"
    return "fresh"


def _scope_org(query, model, organization_id: int | None):
    if organization_id is None or not hasattr(model, "organization_id"):
        return query
    return query.filter(or_(model.organization_id == organization_id, model.organization_id.is_(None)))


def _latest(db: Session, model, column_name: str, organization_id: int | None = None):
    query = db.query(func.max(getattr(model, column_name)))
    query = _scope_org(query, model, organization_id)
    return query.scalar()


def build_source_freshness(db: Session, organization_id: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or utcnow()
    sources = []

    latest_publog = db.query(NsnCatalogImportRun).order_by(NsnCatalogImportRun.completed_at.desc().nullslast()).first()
    latest_publog_at = getattr(latest_publog, "completed_at", None) or getattr(latest_publog, "updated_at", None)
    age = _age_days(latest_publog_at, current_time)
    sources.append({
        "key": "publog",
        "label": "PUB LOG / NSN Catalog",
        "status": _status(age, 45),
        "latest_at": latest_publog_at.isoformat() if latest_publog_at else None,
        "age_days": age,
        "detail": f"{getattr(latest_publog, 'rows_imported', 0) or 0} rows imported" if latest_publog else "No PUB LOG import run found",
    })

    for source_key, label, stale_after in [
        ("SAM", "SAM Ingestion", 3),
        ("DIBBS", "DIBBS Ingestion", 3),
        ("MULTI_SOURCE", "Multi-Source Search", 3),
        ("STATE_LOCAL_ALL", "State/Local Ingestion", 7),
    ]:
        latest_run = (
            db.query(ImportRun)
            .filter(ImportRun.source == source_key)
            .filter(
                ImportRun.organization_id == organization_id
                if organization_id is not None
                else ImportRun.organization_id.is_(None)
            )
            .order_by(ImportRun.completed_at.desc().nullslast(), ImportRun.started_at.desc().nullslast())
            .first()
        )
        latest_at = getattr(latest_run, "completed_at", None) or getattr(latest_run, "started_at", None)
        age = _age_days(latest_at, current_time)
        sources.append(
            {
                "key": source_key.lower(),
                "label": label,
                "status": _status(age, stale_after),
                "latest_at": latest_at.isoformat() if latest_at else None,
                "age_days": age,
                "detail": (
                    f"{getattr(latest_run, 'inserted_count', 0) or 0} inserted, "
                    f"{getattr(latest_run, 'updated_count', 0) or 0} updated, "
                    f"status={getattr(latest_run, 'status', 'unknown')}"
                )
                if latest_run
                else "No ingestion run found",
            }
        )

    source_specs = [
        ("opportunities", "Opportunities", Opportunity, "posted_at", 3, organization_id),
        ("providers", "Provider Database", Provider, "updated_at", 30, organization_id),
        ("nsn_snapshots", "NSN Intelligence Snapshots", NsnIntelligenceSnapshot, "generated_at", 30, None),
        ("award_history", "Award History", AwardHistory, "updated_at", 30, organization_id),
        ("search_jobs", "Background Jobs", SearchJob, "updated_at", 2, organization_id),
    ]
    for key, label, model, column_name, stale_after, org_scope in source_specs:
        latest_at = _latest(db, model, column_name, org_scope)
        age = _age_days(latest_at, current_time)
        sources.append({
            "key": key,
            "label": label,
            "status": _status(age, stale_after),
            "latest_at": latest_at.isoformat() if latest_at else None,
            "age_days": age,
            "detail": f"Stale after {stale_after} days",
        })

    summary = {"fresh": 0, "stale": 0, "missing": 0}
    for source in sources:
        summary[source["status"]] = summary.get(source["status"], 0) + 1
    return {
        "sources": sources,
        "summary": summary,
        "generated_at": current_time.isoformat(),
        "next_recommended_check_at": (current_time + timedelta(days=1)).isoformat(),
    }
