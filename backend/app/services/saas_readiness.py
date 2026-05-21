from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.award_history import AwardHistory
from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.provider import Provider
from app.models.search_job import SearchJob
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact, WorkspaceTask


TENANT_MODELS = [
    Opportunity,
    OpportunityFile,
    WorkspaceArtifact,
    WorkspaceTask,
    VendorLead,
    VendorQuote,
    Provider,
    AwardHistory,
    SearchJob,
    AppSetting,
]

GLOBAL_OR_LEGACY_MODELS = [
    BidSubmission,
]


def build_org_scope_audit(db: Session, organization_id: int | None = None) -> dict[str, Any]:
    rows = []
    for model in TENANT_MODELS:
        table_name = getattr(model, "__tablename__", model.__name__)
        has_org = hasattr(model, "organization_id")
        missing_count = None
        if has_org:
            try:
                missing_count = db.query(func.count(model.id)).filter(model.organization_id.is_(None)).scalar()
            except Exception:
                db.rollback()
                missing_count = None
        rows.append({
            "table": table_name,
            "model": model.__name__,
            "has_organization_id": has_org,
            "nullable_org_rows": missing_count,
            "status": "needs_backfill" if (missing_count or 0) > 0 else "scoped",
        })

    warnings = [
        {
            "table": getattr(model, "__tablename__", model.__name__),
            "model": model.__name__,
            "issue": "No organization_id field. Confirm this table is global or add tenant scoping before production SaaS.",
        }
        for model in GLOBAL_OR_LEGACY_MODELS
        if not hasattr(model, "organization_id")
    ]
    needs_backfill = sum(1 for row in rows if row["status"] == "needs_backfill")
    return {
        "organization_id": organization_id,
        "tables": rows,
        "warnings": warnings,
        "summary": {
            "checked": len(rows),
            "scoped": sum(1 for row in rows if row["status"] == "scoped"),
            "needs_backfill": needs_backfill,
            "warnings": len(warnings),
            "ready_for_saas": needs_backfill == 0 and len(warnings) == 0,
        },
    }
