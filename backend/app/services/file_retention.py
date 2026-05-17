from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.workspace import WorkspaceArtifact
from app.services.storage import delete_reference, delete_reference_tree, storage_root
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle
from sqlalchemy.orm import Session, object_session
from pathlib import Path


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

    if not _downstream_processing_complete(file_record, opportunity):
        return FileRetentionDecision(
            storage_class=storage_class,
            retention_status="retain",
            reason="downstream_processing_incomplete",
            prune_eligible=False,
        )

    return FileRetentionDecision(
        storage_class=storage_class,
        retention_status="eligible_for_prune",
        reason="archived_and_extracted",
        prune_eligible=True,
    )


def mark_opportunity_files_processing_complete(
    db: Session,
    opportunity_id: int,
    *,
    completed: bool,
    source: str,
    details: dict[str, Any] | None = None,
) -> int:
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opportunity_id)
        .all()
    )
    updated = 0
    for file_record in files:
        metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
        retention = dict(metadata.get("_retention") or {})
        retention.update(
            {
                "downstream_complete": bool(completed),
                "last_checked_at": datetime.utcnow().isoformat(),
                "source": source,
            }
        )
        if details:
            retention["details"] = details
        metadata["_retention"] = retention
        file_record.parsed_metadata = metadata
        db.add(file_record)
        updated += 1
    if updated:
        db.commit()
    return updated


def prune_eligible_files_for_system(
    db: Session,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    files = (
        db.query(OpportunityFile)
        .join(Opportunity, Opportunity.id == OpportunityFile.opportunity_id)
        .filter(Opportunity.due_at.is_not(None))
        .filter(Opportunity.due_at < datetime.utcnow() - timedelta(days=30))
        .order_by(Opportunity.due_at.asc().nullslast(), OpportunityFile.id.asc())
        .limit(max(min(limit, 1000), 1))
        .all()
    )

    pruned_count = 0
    skipped_count = 0
    items: list[dict[str, Any]] = []
    cleanup_dirs: set[str] = set()

    for file_record in files:
        opportunity = getattr(file_record, "opportunity", None)
        retention = classify_opportunity_file_retention(file_record, opportunity)
        if not retention.prune_eligible:
            skipped_count += 1
            continue

        original_ref = file_record.file_path
        deleted = delete_reference(original_ref)
        cleanup_dir = _storage_cleanup_dir_for_reference(original_ref)
        if cleanup_dir:
            cleanup_dirs.add(cleanup_dir)
        metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
        metadata["_retention"] = {
            **dict(metadata.get("_retention") or {}),
            "status": "pruned",
            "reason": retention.reason,
            "pruned_at": datetime.utcnow().isoformat(),
            "original_file_path": original_ref,
            "deleted_from_storage": bool(deleted),
        }
        file_record.file_path = f"pruned://opportunity-file/{file_record.id}"
        file_record.parsed_metadata = metadata
        db.add(file_record)
        pruned_count += 1
        items.append(
            {
                "id": file_record.id,
                "opportunity_id": file_record.opportunity_id,
                "filename": file_record.filename,
                "status": "pruned",
                "reason": retention.reason,
                "deleted_from_storage": bool(deleted),
            }
        )

    if pruned_count:
        db.commit()
        _remove_storage_dirs(cleanup_dirs)

    return {
        "pruned_count": pruned_count,
        "skipped_count": skipped_count,
        "items": items,
    }


def prune_closed_opportunity_files_and_storage(
    db: Session,
    opportunity_id: int,
    *,
    require_closed: bool = True,
    source: str = "closed_workspace_cleanup",
) -> dict[str, Any]:
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "opportunity_not_found"}

    lifecycle = derive_opportunity_lifecycle(getattr(opportunity, "due_at", None))
    if require_closed and lifecycle == "ACTIVE":
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "opportunity_active"}

    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opportunity_id)
        .all()
    )
    if not files:
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "no_files"}

    if any(not _closed_workspace_cleanup_ready(file_record, opportunity) for file_record in files):
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "downstream_processing_incomplete"}

    pruned_count = 0
    cleanup_dirs: set[str] = set()
    items: list[dict[str, Any]] = []
    for file_record in files:
        original_ref = getattr(file_record, "file_path", None)
        if not original_ref or str(original_ref).startswith("pruned://"):
            continue
        deleted = delete_reference(original_ref)
        cleanup_dir = _storage_cleanup_dir_for_reference(original_ref)
        if cleanup_dir:
            cleanup_dirs.add(cleanup_dir)
        metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
        metadata["_retention"] = {
            **dict(metadata.get("_retention") or {}),
            "status": "pruned",
            "reason": source,
            "pruned_at": datetime.utcnow().isoformat(),
            "original_file_path": original_ref,
            "deleted_from_storage": bool(deleted),
            "folder_cleanup_requested": True,
        }
        file_record.file_path = f"pruned://opportunity-file/{file_record.id}"
        file_record.parsed_metadata = metadata
        db.add(file_record)
        pruned_count += 1
        items.append(
            {
                "id": file_record.id,
                "filename": file_record.filename,
                "deleted_from_storage": bool(deleted),
            }
        )

    folder_deleted = False
    if pruned_count:
        db.commit()
        folder_deleted = _remove_storage_dirs(cleanup_dirs)

    return {
        "pruned_count": pruned_count,
        "folder_deleted": folder_deleted,
        "items": items,
        "lifecycle": lifecycle,
    }


def _downstream_processing_complete(
    file_record: OpportunityFile,
    opportunity: Opportunity | None = None,
) -> bool:
    parsed_metadata = getattr(file_record, "parsed_metadata", None) or {}
    retention_meta = parsed_metadata.get("_retention") or {}
    if retention_meta.get("downstream_complete") is True:
        return True

    pipeline = parsed_metadata.get("_pipeline") or {}
    if pipeline.get("status") != "completed":
        return False

    if opportunity is None:
        return False

    session = object_session(file_record) or object_session(opportunity)
    if session is None:
        return False

    artifact_types = {
        row[0]
        for row in (
            session.query(WorkspaceArtifact.artifact_type)
            .filter(WorkspaceArtifact.opportunity_id == opportunity.id)
            .all()
        )
    }
    required = {"COMPLIANCE_BRIEF", "SUBMISSION_PACKAGE"}
    return required.issubset(artifact_types)


def _closed_workspace_cleanup_ready(
    file_record: OpportunityFile,
    opportunity: Opportunity | None = None,
) -> bool:
    file_path = getattr(file_record, "file_path", None)
    if isinstance(file_path, str) and file_path.startswith("pruned://"):
        return True
    if not file_path:
        return True
    parsed_metadata = getattr(file_record, "parsed_metadata", None) or {}
    retention_meta = parsed_metadata.get("_retention") or {}
    if retention_meta.get("downstream_complete") is not True:
        return False
    if opportunity is None:
        return False
    return _downstream_processing_complete(file_record, opportunity)


def _storage_cleanup_dir_for_reference(reference: str | None) -> str | None:
    if not reference or not isinstance(reference, str) or reference.startswith(("pruned://", "s3://", "http://", "https://")):
        return None
    try:
        target = Path(reference).resolve()
        root = storage_root().resolve()
        target.relative_to(root)
    except Exception:
        return None
    if target.parent.name.lower() == "documents":
        return str(target.parent.parent)
    return str(target.parent)


def _remove_storage_dirs(cleanup_dirs: set[str]) -> bool:
    removed_any = False
    for directory in sorted(cleanup_dirs):
        if delete_reference_tree(directory):
            removed_any = True
    return removed_any
