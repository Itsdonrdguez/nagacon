from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_run import ImportRun
from app.utils.utc import utcnow


def _stable_hash(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def start_import_run(
    db: Session,
    *,
    source: str,
    run_kind: str,
    request_payload: dict[str, Any] | None = None,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> ImportRun:
    rec = ImportRun(
        organization_id=organization_id,
        user_id=user_id,
        source=source,
        run_kind=run_kind,
        status="started",
        source_hash=_stable_hash(request_payload),
        request_payload=request_payload or None,
        started_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def complete_import_run(
    db: Session,
    rec: ImportRun,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    row_count: int | None = None,
    inserted_count: int | None = None,
    updated_count: int | None = None,
    skipped_count: int | None = None,
    duplicate_count: int | None = None,
) -> ImportRun:
    rec.status = status
    rec.result_payload = result_payload or None
    rec.error_message = error_message
    rec.row_count = row_count
    rec.inserted_count = inserted_count
    rec.updated_count = updated_count
    rec.skipped_count = skipped_count
    rec.duplicate_count = duplicate_count
    rec.completed_at = utcnow()
    rec.updated_at = utcnow()
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec
