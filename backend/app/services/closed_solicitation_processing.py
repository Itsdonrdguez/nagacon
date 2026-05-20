from __future__ import annotations

import hashlib
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.closed_solicitation_processing import ClosedSolicitationProcessingRecord
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.price_history import PriceHistory
from app.models.provider import Provider
from app.models.vendor import VendorLead, VendorQuote
from app.services.app_settings_service import get_setting
from app.services.intelligence.nsn_intelligence_service import build_nsn_research_target
from app.services.pdf_service import effective_pdf_download_root
from app.services.storage import delete_reference, delete_reference_tree, local_temp_path, storage_root
from app.utils.opportunity_lifecycle import derive_opportunity_lifecycle


STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_PROCESSED_DELETED = "processed_deleted"
STATUS_PROCESSED_RETAINED = "processed_retained"
STATUS_PROCESSED_FAILED = "processed_failed"
STATUS_NEEDS_REVIEW = "needs_review"


def process_closed_solicitation_file(
    db: Session,
    file_record: OpportunityFile,
    *,
    opportunity: Opportunity | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    now = datetime.utcnow()
    opportunity = opportunity or getattr(file_record, "opportunity", None)
    if opportunity is None and getattr(file_record, "opportunity_id", None) is not None:
        opportunity = db.query(Opportunity).filter(Opportunity.id == file_record.opportunity_id).first()

    metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
    retention = dict(metadata.get("_retention") or {})
    closed_meta = dict(retention.get("closed_processing") or {})

    if str(getattr(file_record, "file_path", "") or "").startswith("pruned://"):
        existing = _find_processing_record(
            db,
            record_id=closed_meta.get("audit_record_id"),
            opportunity_id=getattr(file_record, "opportunity_id", None),
            file_sha256=closed_meta.get("file_sha256"),
        )
        return {
            "status": "already_processed",
            "extraction_status": getattr(existing, "extraction_status", None) or STATUS_PROCESSED_DELETED,
            "audit_record_id": getattr(existing, "id", None),
            "deleted": True,
            "folder_path": _storage_cleanup_dir_for_reference(
                db,
                closed_meta.get("original_file_path"),
                organization_id=getattr(file_record, "organization_id", None) or getattr(opportunity, "organization_id", None),
            ),
        }

    original_ref = getattr(file_record, "file_path", None)
    if not original_ref:
        return _mark_processing_issue(
            db,
            file_record,
            opportunity=opportunity,
            status=STATUS_NEEDS_REVIEW,
            message="file_path_missing",
            source_url=source_url,
            when=now,
        )

    try:
        fingerprint = _compute_file_fingerprint(file_record)
    except Exception as exc:
        return _mark_processing_issue(
            db,
            file_record,
            opportunity=opportunity,
            status=STATUS_NEEDS_REVIEW,
            message=f"file_fingerprint_failed: {exc}",
            source_url=source_url,
            when=now,
        )

    existing = _find_processing_record(
        db,
        record_id=closed_meta.get("audit_record_id"),
        opportunity_id=getattr(file_record, "opportunity_id", None),
        file_sha256=fingerprint["file_sha256"],
    )
    if existing and getattr(existing, "extraction_status", None) == STATUS_PROCESSED_DELETED:
        _update_closed_processing_metadata(
            db,
            file_record,
            audit_record=existing,
            original_file_path=existing.local_path_before_deletion or original_ref,
            deleted=True,
            when=now,
        )
        return {
            "status": "already_processed",
            "extraction_status": STATUS_PROCESSED_DELETED,
            "audit_record_id": existing.id,
            "deleted": True,
            "folder_path": _storage_cleanup_dir_for_reference(
                db,
                existing.local_path_before_deletion or original_ref,
                organization_id=getattr(file_record, "organization_id", None) or getattr(opportunity, "organization_id", None),
            ),
        }

    queue_snapshot = _build_queue_snapshot(file_record, opportunity, fingerprint, source_url, now)
    try:
        audit_record = _upsert_processing_record(
            db,
            file_record=file_record,
            opportunity=opportunity,
            snapshot=queue_snapshot,
            status=STATUS_QUEUED,
            error_message=None,
            processed_at=None,
            deletion_timestamp=None,
            existing=existing,
        )
        db.commit()
        db.refresh(audit_record)
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        return {
            "status": "audit_persist_failed",
            "extraction_status": STATUS_NEEDS_REVIEW,
            "deleted": False,
            "error": str(exc),
        }

    try:
        snapshot = _build_closed_solicitation_snapshot(
            db,
            file_record=file_record,
            opportunity=opportunity,
            source_url=source_url,
            fingerprint=fingerprint,
            processed_at=now,
        )
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        try:
            audit_record = _upsert_processing_record(
                db,
                file_record=file_record,
                opportunity=opportunity,
                snapshot=queue_snapshot,
                status=STATUS_PROCESSED_FAILED,
                error_message=str(exc),
                processed_at=now,
                deletion_timestamp=None,
                existing=audit_record,
            )
            _update_closed_processing_metadata(
                db,
                file_record,
                audit_record=audit_record,
                original_file_path=original_ref,
                deleted=False,
                when=now,
            )
            db.commit()
        except Exception:
            if hasattr(db, "rollback"):
                db.rollback()
        return {
            "status": "extraction_failed",
            "extraction_status": STATUS_PROCESSED_FAILED,
            "audit_record_id": getattr(audit_record, "id", None),
            "deleted": False,
            "error": str(exc),
        }

    try:
        audit_record = _upsert_processing_record(
            db,
            file_record=file_record,
            opportunity=opportunity,
            snapshot=snapshot,
            status=STATUS_PROCESSING,
            error_message=None,
            processed_at=now,
            deletion_timestamp=None,
            existing=audit_record,
        )
        _update_closed_processing_metadata(
            db,
            file_record,
            audit_record=audit_record,
            original_file_path=original_ref,
            deleted=False,
            when=now,
        )
        db.commit()
        db.refresh(audit_record)
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        return {
            "status": "audit_persist_failed",
            "extraction_status": STATUS_NEEDS_REVIEW,
            "audit_record_id": getattr(audit_record, "id", None),
            "deleted": False,
            "error": str(exc),
        }

    deleted = False
    delete_error: str | None = None
    try:
        deleted = bool(delete_reference(original_ref))
    except Exception as exc:
        delete_error = str(exc)

    try:
        if deleted:
            file_record.file_path = f"pruned://opportunity-file/{file_record.id}"
            audit_record = _upsert_processing_record(
                db,
                file_record=file_record,
                opportunity=opportunity,
                snapshot=snapshot,
                status=STATUS_PROCESSED_DELETED,
                error_message=None,
                processed_at=now,
                deletion_timestamp=now,
                existing=audit_record,
            )
        else:
            delete_error = delete_error or "delete_reference_returned_false"
            audit_record = _upsert_processing_record(
                db,
                file_record=file_record,
                opportunity=opportunity,
                snapshot=snapshot,
                status=STATUS_PROCESSED_RETAINED,
                error_message=delete_error,
                processed_at=now,
                deletion_timestamp=None,
                existing=audit_record,
            )

        _update_closed_processing_metadata(
            db,
            file_record,
            audit_record=audit_record,
            original_file_path=original_ref,
            deleted=deleted,
            when=now,
        )
        db.commit()
        db.refresh(audit_record)
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        return {
            "status": "post_delete_audit_failed",
            "extraction_status": STATUS_NEEDS_REVIEW,
            "audit_record_id": getattr(audit_record, "id", None),
            "deleted": deleted,
            "error": str(exc),
        }

    return {
        "status": "processed" if deleted else "retained",
        "extraction_status": audit_record.extraction_status,
        "audit_record_id": audit_record.id,
        "deleted": deleted,
        "folder_path": (
            _storage_cleanup_dir_for_reference(
                db,
                original_ref,
                organization_id=getattr(file_record, "organization_id", None) or getattr(opportunity, "organization_id", None),
            )
            if deleted
            else None
        ),
        "error": delete_error,
    }


def process_closed_solicitation_files_for_opportunity(
    db: Session,
    opportunity_id: int,
    *,
    require_closed: bool = True,
    source: str = "closed_workspace_cleanup",
) -> dict[str, Any]:
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "opportunity_not_found"}

    files = db.query(OpportunityFile).filter(OpportunityFile.opportunity_id == opportunity_id).all()
    if not files:
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "no_files"}

    lifecycle = derive_opportunity_lifecycle(getattr(opportunity, "due_at", None))
    if require_closed and lifecycle == "ACTIVE":
        return {"pruned_count": 0, "folder_deleted": False, "skipped_reason": "opportunity_active"}

    items: list[dict[str, Any]] = []
    cleanup_dirs: set[str] = set()
    pruned_count = 0
    retained_count = 0

    for file_record in files:
        if not _file_ready_for_closed_processing(file_record):
            retained_count += 1
            items.append(
                {
                    "id": getattr(file_record, "id", None),
                    "filename": getattr(file_record, "filename", None),
                    "status": "skipped",
                    "reason": "downstream_processing_incomplete",
                }
            )
            continue

        result = process_closed_solicitation_file(db, file_record, opportunity=opportunity, source_url=getattr(file_record, "source_url", None))
        item = {
            "id": getattr(file_record, "id", None),
            "filename": getattr(file_record, "filename", None),
            "status": result.get("extraction_status"),
            "deleted_from_storage": bool(result.get("deleted")),
            "audit_record_id": result.get("audit_record_id"),
        }
        if result.get("error"):
            item["error"] = result.get("error")
        items.append(item)
        if result.get("deleted"):
            pruned_count += 1
            if result.get("folder_path"):
                cleanup_dirs.add(str(result["folder_path"]))
        else:
            retained_count += 1

    folder_deleted = False
    if pruned_count and retained_count == 0:
        folder_deleted = _remove_storage_dirs(cleanup_dirs)

    return {
        "pruned_count": pruned_count,
        "retained_count": retained_count,
        "folder_deleted": folder_deleted,
        "items": items,
        "lifecycle": lifecycle,
        "source": source,
    }


def _mark_processing_issue(
    db: Session,
    file_record: OpportunityFile,
    *,
    opportunity: Opportunity | None,
    status: str,
    message: str,
    source_url: str | None,
    when: datetime,
) -> dict[str, Any]:
    fallback_hash = hashlib.sha256(
        f"{getattr(file_record, 'opportunity_id', '')}:{getattr(file_record, 'id', '')}:{getattr(file_record, 'filename', '')}:{getattr(file_record, 'file_path', '')}".encode("utf-8")
    ).hexdigest()
    snapshot = _build_queue_snapshot(
        file_record,
        opportunity,
        {
            "file_sha256": fallback_hash,
            "file_size_bytes": None,
            "source_updated_at": getattr(file_record, "created_at", None),
        },
        source_url,
        when,
    )
    try:
        audit_record = _upsert_processing_record(
            db,
            file_record=file_record,
            opportunity=opportunity,
            snapshot=snapshot,
            status=status,
            error_message=message,
            processed_at=when,
            deletion_timestamp=None,
            existing=None,
        )
        _update_closed_processing_metadata(
            db,
            file_record,
            audit_record=audit_record,
            original_file_path=getattr(file_record, "file_path", None),
            deleted=False,
            when=when,
        )
        db.commit()
        return {
            "status": "retained",
            "extraction_status": status,
            "audit_record_id": getattr(audit_record, "id", None),
            "deleted": False,
            "error": message,
        }
    except Exception:
        if hasattr(db, "rollback"):
            db.rollback()
        return {
            "status": "retained",
            "extraction_status": status,
            "deleted": False,
            "error": message,
        }


def _build_queue_snapshot(
    file_record: OpportunityFile,
    opportunity: Opportunity | None,
    fingerprint: dict[str, Any],
    source_url: str | None,
    when: datetime,
) -> dict[str, Any]:
    parsed = dict(getattr(file_record, "parsed_metadata", None) or {})
    opportunity_parsed = dict(getattr(opportunity, "parsed_json", None) or {}) if opportunity else {}
    return {
        "solicitation_number": (
            getattr(opportunity, "solicitation_number", None)
            or parsed.get("solicitation_number")
            or getattr(file_record, "filename", None)
        ),
        "nsn": parsed.get("nsn") or opportunity_parsed.get("nsn"),
        "part_numbers": _clean_unique_strings(parsed.get("part_numbers") or []),
        "vendor_names": [],
        "cage_codes": _clean_unique_strings(parsed.get("cage_codes") or []),
        "pricing_history_notes": None,
        "original_source_file_name": getattr(file_record, "filename", None),
        "original_source_url": source_url or getattr(file_record, "source_url", None),
        "local_path_before_deletion": getattr(file_record, "file_path", None),
        "file_size_bytes": fingerprint.get("file_size_bytes"),
        "file_sha256": fingerprint["file_sha256"],
        "source_updated_at": fingerprint.get("source_updated_at") or getattr(file_record, "created_at", None) or when,
        "processed_at": when,
        "last_seen_at": when,
        "last_processed_at": when,
    }


def _build_closed_solicitation_snapshot(
    db: Session,
    *,
    file_record: OpportunityFile,
    opportunity: Opportunity | None,
    source_url: str | None,
    fingerprint: dict[str, Any],
    processed_at: datetime,
) -> dict[str, Any]:
    if opportunity is None:
        raise ValueError("opportunity_not_found")
    if not _file_ready_for_closed_processing(file_record):
        raise ValueError("downstream_processing_incomplete")

    parsed = dict(getattr(file_record, "parsed_metadata", None) or {})
    target = build_nsn_research_target(db, opportunity)
    lead_rows = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity.id).all()
    quote_rows = db.query(VendorQuote).filter(VendorQuote.opportunity_id == opportunity.id).all()
    price_rows = db.query(PriceHistory).filter(PriceHistory.opportunity_id == opportunity.id).all()
    provider_rows = db.query(Provider).all()

    cage_name_map = _build_cage_name_map(provider_rows)

    part_numbers = _clean_unique_strings(
        list(target.get("part_numbers") or [])
        + list(parsed.get("part_numbers") or [])
        + [getattr(row, "part_number", None) for row in lead_rows]
        + [getattr(row, "part_number", None) for row in quote_rows]
    )

    cage_codes = _clean_unique_strings(
        list(target.get("manufacturer_cages") or [])
        + list(parsed.get("cage_codes") or [])
        + [getattr(row, "cage", None) for row in lead_rows]
        + [getattr(row, "cage", None) for row in quote_rows]
        + [getattr(row, "cage", None) for row in price_rows]
    )

    vendor_names = _clean_unique_strings(
        [
            _enriched_vendor_name(cage_name_map, cage=getattr(row, "cage", None), vendor=getattr(row, "company_name", None))
            for row in lead_rows
        ]
        + [
            _enriched_vendor_name(cage_name_map, cage=getattr(row, "cage", None), vendor=getattr(row, "company_name", None))
            for row in quote_rows
        ]
        + [
            _enriched_vendor_name(cage_name_map, cage=getattr(row, "cage", None), vendor=getattr(row, "supplier_name", None))
            for row in price_rows
        ]
        + [
            _enriched_vendor_name(cage_name_map, cage=None, vendor=name)
            for name in target.get("manufacturer_names") or []
        ]
    )

    pricing_notes = _build_pricing_history_notes(price_rows, file_record_id=getattr(file_record, "id", None))

    return {
        "solicitation_number": getattr(opportunity, "solicitation_number", None) or parsed.get("solicitation_number"),
        "nsn": target.get("nsn") or parsed.get("nsn") or getattr(opportunity, "solicitation_number", None),
        "part_numbers": part_numbers,
        "vendor_names": vendor_names,
        "cage_codes": cage_codes,
        "pricing_history_notes": pricing_notes,
        "original_source_file_name": getattr(file_record, "filename", None),
        "original_source_url": source_url or getattr(file_record, "source_url", None),
        "local_path_before_deletion": getattr(file_record, "file_path", None),
        "file_size_bytes": fingerprint.get("file_size_bytes"),
        "file_sha256": fingerprint["file_sha256"],
        "source_updated_at": fingerprint.get("source_updated_at") or getattr(file_record, "created_at", None) or processed_at,
        "processed_at": processed_at,
        "last_seen_at": processed_at,
        "last_processed_at": processed_at,
    }


def _upsert_processing_record(
    db: Session,
    *,
    file_record: OpportunityFile,
    opportunity: Opportunity | None,
    snapshot: dict[str, Any],
    status: str,
    error_message: str | None,
    processed_at: datetime | None,
    deletion_timestamp: datetime | None,
    existing: ClosedSolicitationProcessingRecord | None,
) -> ClosedSolicitationProcessingRecord:
    record = existing or _find_processing_record(
        db,
        record_id=None,
        opportunity_id=getattr(file_record, "opportunity_id", None),
        file_sha256=snapshot["file_sha256"],
    )
    if record is None:
        record = ClosedSolicitationProcessingRecord(
            organization_id=getattr(file_record, "organization_id", None) or getattr(opportunity, "organization_id", None),
            opportunity_id=getattr(file_record, "opportunity_id", None),
            opportunity_file_id=getattr(file_record, "id", None),
            file_sha256=snapshot["file_sha256"],
        )

    record.organization_id = getattr(file_record, "organization_id", None) or getattr(opportunity, "organization_id", None)
    record.opportunity_id = getattr(file_record, "opportunity_id", None)
    record.opportunity_file_id = getattr(file_record, "id", None)
    record.solicitation_number = _prefer_string(record.solicitation_number, snapshot.get("solicitation_number"))
    record.nsn = _prefer_string(record.nsn, snapshot.get("nsn"))
    record.part_numbers = _merge_string_lists(record.part_numbers, snapshot.get("part_numbers"))
    record.vendor_names = _merge_string_lists(record.vendor_names, snapshot.get("vendor_names"))
    record.cage_codes = _merge_string_lists(record.cage_codes, snapshot.get("cage_codes"))
    record.pricing_history_notes = _prefer_longer(record.pricing_history_notes, snapshot.get("pricing_history_notes"))
    record.original_source_file_name = _prefer_string(record.original_source_file_name, snapshot.get("original_source_file_name"))
    record.original_source_url = _prefer_string(record.original_source_url, snapshot.get("original_source_url"))
    record.local_path_before_deletion = _prefer_string(record.local_path_before_deletion, snapshot.get("local_path_before_deletion"))
    record.file_size_bytes = snapshot.get("file_size_bytes") or record.file_size_bytes
    record.file_sha256 = snapshot["file_sha256"]
    record.extraction_status = status
    record.processed_at = processed_at or record.processed_at
    record.deletion_timestamp = deletion_timestamp or record.deletion_timestamp
    record.error_message = error_message
    record.last_seen_at = snapshot.get("last_seen_at") or datetime.utcnow()
    record.last_processed_at = snapshot.get("last_processed_at") or processed_at or record.last_processed_at
    record.source_updated_at = snapshot.get("source_updated_at") or record.source_updated_at

    db.add(record)
    db.flush()
    return record


def _find_processing_record(
    db: Session,
    *,
    record_id: int | None,
    opportunity_id: int | None,
    file_sha256: str | None,
) -> ClosedSolicitationProcessingRecord | None:
    query = db.query(ClosedSolicitationProcessingRecord)
    if record_id:
        return query.filter(ClosedSolicitationProcessingRecord.id == record_id).first()
    if opportunity_id is not None and file_sha256:
        return (
            query
            .filter(ClosedSolicitationProcessingRecord.opportunity_id == opportunity_id)
            .filter(ClosedSolicitationProcessingRecord.file_sha256 == file_sha256)
            .first()
        )
    return None


def _update_closed_processing_metadata(
    db: Session,
    file_record: OpportunityFile,
    *,
    audit_record: ClosedSolicitationProcessingRecord,
    original_file_path: str | None,
    deleted: bool,
    when: datetime,
) -> None:
    metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
    retention = dict(metadata.get("_retention") or {})
    retention["closed_processing"] = {
        "audit_record_id": getattr(audit_record, "id", None),
        "file_sha256": getattr(audit_record, "file_sha256", None),
        "status": getattr(audit_record, "extraction_status", None),
        "original_file_path": original_file_path,
        "processed_at": when.isoformat(),
        "deleted": bool(deleted),
        "deletion_timestamp": when.isoformat() if deleted else None,
        "folder_cleanup_pending": bool(deleted),
    }
    metadata["_retention"] = retention
    file_record.parsed_metadata = metadata
    db.add(file_record)


def _compute_file_fingerprint(file_record: OpportunityFile) -> dict[str, Any]:
    reference = getattr(file_record, "file_path", None)
    if not reference:
        raise ValueError("file_path_missing")
    suffix = Path(getattr(file_record, "filename", None) or reference).suffix
    hasher = hashlib.sha256()
    with local_temp_path(reference, suffix=suffix) as local_path:
        with local_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        stat = local_path.stat()
        return {
            "file_sha256": hasher.hexdigest(),
            "file_size_bytes": stat.st_size,
            "source_updated_at": datetime.fromtimestamp(stat.st_mtime),
        }


def _build_pricing_history_notes(rows: list[PriceHistory], *, file_record_id: int | None) -> str | None:
    relevant = [row for row in rows if file_record_id is not None and getattr(row, "source_file_id", None) == file_record_id]
    if not relevant:
        relevant = list(rows)
    lines: list[str] = []
    for row in relevant[:5]:
        bits: list[str] = []
        if getattr(row, "supplier_name", None):
            bits.append(str(row.supplier_name))
        elif getattr(row, "cage", None):
            bits.append(f"CAGE {row.cage}")
        if getattr(row, "unit_price", None) is not None:
            bits.append(f"unit {row.unit_price}")
        if getattr(row, "award_date", None):
            bits.append(f"award {row.award_date}")
        if getattr(row, "source_label", None):
            bits.append(f"source {row.source_label}")
        if bits:
            lines.append(" | ".join(bits))
    return "\n".join(lines) if lines else None


def _build_cage_name_map(provider_rows: list[Provider]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for provider in provider_rows:
        cage = _clean(getattr(provider, "cage", None))
        if not cage:
            continue
        name = _clean(getattr(provider, "canonical_name", None)) or _clean(getattr(provider, "company_name", None))
        if not name:
            continue
        current = mapping.get(cage.upper())
        if not current or current.upper().startswith("CAGE "):
            mapping[cage.upper()] = name
    return mapping


def _enriched_vendor_name(cage_name_map: dict[str, str], *, cage: str | None, vendor: str | None) -> str | None:
    clean_cage = _clean(cage)
    if clean_cage:
        enriched = cage_name_map.get(clean_cage.upper())
        if enriched:
            return enriched
    return _clean(vendor) or (f"CAGE {clean_cage}" if clean_cage else None)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _clean_unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        clean = _clean(value)
        if not clean:
            continue
        key = clean.upper()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output


def _merge_string_lists(existing: list[str] | None, incoming: list[str] | None) -> list[str] | None:
    merged = _clean_unique_strings(list(existing or []) + list(incoming or []))
    return merged or None


def _prefer_string(existing: str | None, incoming: str | None) -> str | None:
    current = _clean(existing)
    newer = _clean(incoming)
    if not current:
        return newer
    if not newer:
        return current
    if len(newer) > len(current):
        return newer
    return current


def _prefer_longer(existing: str | None, incoming: str | None) -> str | None:
    current = _clean(existing)
    newer = _clean(incoming)
    if not current:
        return newer
    if not newer:
        return current
    return newer if len(newer) >= len(current) else current


def _file_ready_for_closed_processing(file_record: OpportunityFile) -> bool:
    file_path = getattr(file_record, "file_path", None)
    if isinstance(file_path, str) and file_path.startswith("pruned://"):
        return True
    if not file_path:
        return False
    if not getattr(file_record, "extracted_text", None):
        return False
    parsed_metadata = dict(getattr(file_record, "parsed_metadata", None) or {})
    if not parsed_metadata:
        return False
    retention_meta = dict(parsed_metadata.get("_retention") or {})
    opportunity = getattr(file_record, "opportunity", None)
    if retention_meta.get("downstream_complete") is not True:
        from app.services.file_retention import _downstream_processing_complete

        if not _downstream_processing_complete(
            file_record,
            opportunity,
        ):
            return False
    pipeline = dict(parsed_metadata.get("_pipeline") or {})
    if pipeline.get("review_required") is True:
        return False
    return True


def _storage_cleanup_dir_for_reference(
    db: Session,
    reference: str | None,
    *,
    organization_id: int | None = None,
) -> str | None:
    if not reference or not isinstance(reference, str) or reference.startswith(("pruned://", "s3://", "http://", "https://")):
        return None
    try:
        target = Path(reference).resolve()
    except Exception:
        return None
    cleanup_dir = target.parent.parent if target.parent.name.lower() == "documents" else target.parent
    if cleanup_dir == cleanup_dir.parent or str(cleanup_dir) == cleanup_dir.anchor:
        return None

    for root in _cleanup_root_candidates(db, organization_id=organization_id):
        try:
            target.relative_to(root)
            return str(cleanup_dir)
        except Exception:
            continue

    if target.exists() and cleanup_dir.exists():
        return str(cleanup_dir)
    return None


def _cleanup_root_candidates(db: Session, *, organization_id: int | None = None) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(candidate: str | Path | None) -> None:
        if not candidate:
            return
        try:
            path = Path(candidate).resolve()
        except Exception:
            return
        if path.suffix:
            path = path.parent
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    add(storage_root())
    add(effective_pdf_download_root(db, organization_id=organization_id))
    configured_pdf_root = get_setting(db, "pdf_download_path", default="", organization_id=organization_id) or ""
    add(configured_pdf_root)
    return roots


def _remove_storage_dirs(cleanup_dirs: set[str]) -> bool:
    removed_any = False
    for directory in sorted(cleanup_dirs):
        try:
            target = Path(directory)
            _prune_disposable_residue(target)
            if not target.exists():
                removed_any = True
                continue
            if delete_reference_tree(directory):
                removed_any = True
        except Exception:
            continue
    return removed_any


def _prune_disposable_residue(directory: Path) -> None:
    try:
        if not directory.exists() or not directory.is_dir():
            return
    except Exception:
        return

    for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_file() and _is_disposable_residue_file(path):
                path.unlink(missing_ok=True)
        except Exception:
            continue

    try:
        remaining_files = [path for path in directory.rglob("*") if path.is_file()]
    except Exception:
        remaining_files = []
    if not remaining_files:
        try:
            shutil.rmtree(directory, onerror=_clear_readonly_and_retry)
        except Exception:
            pass
        return

    for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except Exception:
            continue

    try:
        if not any(directory.iterdir()):
            directory.rmdir()
    except Exception:
        pass


def _is_disposable_residue_file(path: Path) -> bool:
    name = path.name.lower()
    return name == "desktop.ini" or name.endswith("_official_pdf_debug.json")


def _clear_readonly_and_retry(func, path, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass
