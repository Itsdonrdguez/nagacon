from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle


@dataclass
class FileRetentionDecision:
    storage_class: str
    retention_status: str
    reason: str
    prune_eligible: bool


def classify_opportunity_file_retention(
    file_record: OpportunityFile,
    opportunity: Opportunity | None = None,
    *,
    now: datetime | None = None,
) -> FileRetentionDecision:
    parsed_metadata = getattr(file_record, "parsed_metadata", None) or {}
    pipeline = parsed_metadata.get("_pipeline") or {}
    document_type = str(parsed_metadata.get("document_type") or "").upper()
    file_type = str(getattr(file_record, "file_type", "") or "").upper()
    lifecycle = derive_opportunity_lifecycle(getattr(opportunity, "due_at", None), now=now) if opportunity else "ACTIVE"

    storage_class = "cache" if file_type == "PDF_FALLBACK_SNAPSHOT" else "core"

    file_path = getattr(file_record, "file_path", None)
    if isinstance(file_path, str) and file_path.startswith("pruned://"):
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="pruned",
            reason="file_pruned",
            prune_eligible=False,
        )

    if not file_path:
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="pruned",
            reason="file_path_missing",
            prune_eligible=False,
        )

    if lifecycle in {"ACTIVE", "RECENTLY_CLOSED"}:
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="retain",
            reason="active_or_recently_closed",
            prune_eligible=False,
        )

    if not getattr(file_record, "extracted_text", None) or not parsed_metadata:
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="retain",
            reason="extraction_incomplete",
            prune_eligible=False,
        )

    if bool(pipeline.get("review_required")):
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="retain",
            reason="review_required",
            prune_eligible=False,
        )

    if document_type in {"AMENDMENT", "STATEMENT_OF_WORK"}:
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="retain",
            reason="evidence_preserve_document_type",
            prune_eligible=False,
        )

    return FileRetentionDecision(
        storage_class=storage_class,
        retention_status="eligible_for_prune",
        reason="archived_and_extracted",
        prune_eligible=True,
    )
