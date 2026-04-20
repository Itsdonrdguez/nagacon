from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnCatalogImportRun
from app.models.opportunity import Opportunity
from app.services.nsn_catalog.normalizer import normalize_nsn
from app.services.nsn_catalog.publog_decomp import (
    DEFAULT_PUBLOG_DIR,
    DEFAULT_PUBLOG_ZIP,
    ensure_publog_workdir,
    import_publog_nsn,
    _read_publog_version,
)


PACKAGE_SOURCE_NAME = "PUB_LOG_PACKAGE"
NSN_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?\d{2}[-\s]?\d{3}[-\s]?\d{4}|\d{13})\b")


def publog_paths(
    *,
    zip_path: str | Path | None = None,
    publog_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    archive_path = Path(zip_path or os.getenv("PUBLOG_DVD_ZIP") or DEFAULT_PUBLOG_ZIP)
    root = Path(publog_dir or os.getenv("PUBLOG_DATA_DIR") or DEFAULT_PUBLOG_DIR)
    return archive_path, root


def get_publog_package_status(
    db: Session,
    *,
    zip_path: str | Path | None = None,
    publog_dir: str | Path | None = None,
) -> dict[str, Any]:
    archive_path, root = publog_paths(zip_path=zip_path, publog_dir=publog_dir)
    prep = ensure_publog_workdir(zip_path=archive_path, publog_dir=root)
    latest_run = (
        db.query(NsnCatalogImportRun)
        .filter(NsnCatalogImportRun.source_name == PACKAGE_SOURCE_NAME)
        .order_by(NsnCatalogImportRun.completed_at.desc().nullslast(), NsnCatalogImportRun.created_at.desc())
        .first()
    )
    zip_info = _zip_info(archive_path, compute_hash=False)
    source_version = _read_publog_version(root)
    return {
        "status": "ready" if prep.get("status") == "ready" and archive_path.exists() else prep.get("status"),
        "zip_path": str(archive_path),
        "publog_dir": str(root),
        "zip": zip_info,
        "source_version": source_version,
        "prep": prep,
        "latest_run": _run_payload(latest_run),
    }


def sync_publog_package(
    db: Session,
    *,
    zip_path: str | Path | None = None,
    publog_dir: str | Path | None = None,
    source_version: str | None = None,
    nsns: list[str] | None = None,
    target_limit: int = 250,
    dry_run: bool = False,
    force: bool = False,
    compute_hash: bool = False,
    progress_callback=None,
) -> dict[str, Any]:
    archive_path, root = publog_paths(zip_path=zip_path, publog_dir=publog_dir)
    prep = ensure_publog_workdir(zip_path=archive_path, publog_dir=root)
    if prep.get("status") != "ready":
        return {
            "status": prep.get("status") or "not_ready",
            "error": "PUB LOG package is not ready.",
            "prep": prep,
            "zip_path": str(archive_path),
            "publog_dir": str(root),
        }

    version = source_version or _read_publog_version(root) or _fallback_source_version(archive_path)
    zip_info = _zip_info(archive_path, compute_hash=compute_hash)
    targets = _normalize_targets(nsns or discover_publog_target_nsns(db, limit=target_limit))
    if not targets:
        return {
            "status": "no_targets",
            "source_version": version,
            "zip": zip_info,
            "prep": prep,
            "targets": [],
        }

    if not dry_run and not force and _already_completed(db, version, archive_path):
        return {
            "status": "skipped",
            "reason": "PUB LOG package version already synced.",
            "source_version": version,
            "zip": zip_info,
            "targets": targets,
        }

    run = NsnCatalogImportRun(
        source_name=PACKAGE_SOURCE_NAME,
        source_version=version,
        source_file=str(archive_path),
        status="running",
        started_at=datetime.utcnow(),
        rows_seen=len(targets),
        rows_imported=0,
        metadata_json={
            "dry_run": dry_run,
            "zip": zip_info,
            "publog_dir": str(root),
            "target_limit": target_limit,
            "targets": targets,
        },
    )
    if not dry_run:
        db.add(run)
        db.commit()
        db.refresh(run)

    imported = 0
    failed = 0
    results: list[dict[str, Any]] = []
    try:
        total = len(targets)
        for index, nsn in enumerate(targets, start=1):
            _emit(progress_callback, "publog", f"Importing PUB LOG NSN {nsn}", index, total)
            result = import_publog_nsn(
                db,
                nsn,
                publog_dir=root,
                source_version=version,
                dry_run=dry_run,
            )
            compact = result.get("compact_nsn") or nsn
            item = {
                "nsn": result.get("nsn") or nsn,
                "compact_nsn": compact,
                "status": result.get("status"),
                "identity_rows": result.get("identity_rows", 0),
                "part_rows": result.get("part_rows", 0),
                "cage_rows": result.get("cage_rows", 0),
                "references_created": result.get("references_created", 0),
                "references_updated": result.get("references_updated", 0),
            }
            results.append(item)
            if result.get("status") == "ok":
                imported += 1
            else:
                failed += 1
        if not dry_run:
            run.status = "completed" if failed == 0 else "completed_with_errors"
            run.rows_imported = imported
            run.completed_at = datetime.utcnow()
            run.metadata_json = {
                **(run.metadata_json or {}),
                "imported": imported,
                "failed": failed,
                "results": results[:500],
            }
            db.add(run)
            db.commit()
    except Exception as exc:
        if not dry_run:
            db.rollback()
            run.status = "failed"
            run.rows_imported = imported
            run.error = str(exc)
            run.completed_at = datetime.utcnow()
            db.add(run)
            db.commit()
        raise

    return {
        "status": "ok" if failed == 0 else "completed_with_errors",
        "source_name": PACKAGE_SOURCE_NAME,
        "source_version": version,
        "zip": zip_info,
        "prep": prep,
        "dry_run": dry_run,
        "targets": targets,
        "target_count": len(targets),
        "imported": imported,
        "failed": failed,
        "results": results,
        "import_run_id": None if dry_run else run.id,
    }


def discover_publog_target_nsns(db: Session, *, limit: int = 250) -> list[str]:
    found: dict[str, str] = {}
    rows = (
        db.query(Opportunity)
        .order_by(Opportunity.posted_at.desc().nullslast(), Opportunity.id.desc())
        .limit(max(limit * 8, limit))
        .all()
    )
    for row in rows:
        for raw in _opportunity_search_strings(row):
            for match in NSN_PATTERN.findall(raw or ""):
                target = normalize_nsn(match)
                if target and target.compact not in found:
                    found[target.compact] = target.nsn
                    if len(found) >= limit:
                        return list(found.values())
    return list(found.values())


def _opportunity_search_strings(row: Opportunity) -> list[str]:
    values = [
        row.source_opportunity_id,
        row.solicitation_number,
        row.title,
        row.raw_text,
        row.fsc,
    ]
    for payload in [row.parsed_json, row.raw_payload]:
        if payload:
            try:
                values.append(json.dumps(payload, default=str))
            except TypeError:
                values.append(str(payload))
    return [str(value) for value in values if value]


def _normalize_targets(values: list[str]) -> list[str]:
    out: dict[str, str] = {}
    for value in values:
        target = normalize_nsn(value)
        if target:
            out[target.compact] = target.nsn
    return list(out.values())


def _already_completed(db: Session, source_version: str | None, archive_path: Path) -> bool:
    if not source_version:
        return False
    return (
        db.query(NsnCatalogImportRun)
        .filter(
            NsnCatalogImportRun.source_name == PACKAGE_SOURCE_NAME,
            NsnCatalogImportRun.source_version == source_version,
            NsnCatalogImportRun.source_file == str(archive_path),
            NsnCatalogImportRun.status.in_(["completed", "completed_with_errors"]),
        )
        .first()
        is not None
    )


def _zip_info(path: Path, *, compute_hash: bool) -> dict[str, Any]:
    info = {
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None,
        "sha256": None,
        "member_count": None,
    }
    if path.exists():
        try:
            with zipfile.ZipFile(path) as archive:
                info["member_count"] = len(archive.namelist())
        except zipfile.BadZipFile:
            info["bad_zip"] = True
        if compute_hash:
            info["sha256"] = _sha256(path)
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fallback_source_version(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")


def _run_payload(run: NsnCatalogImportRun | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "id": run.id,
        "source_name": run.source_name,
        "source_version": run.source_version,
        "source_file": run.source_file,
        "status": run.status,
        "rows_seen": run.rows_seen,
        "rows_imported": run.rows_imported,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "metadata": run.metadata_json,
    }


def _emit(callback, source: str, label: str, completed_steps: int, total_steps: int) -> None:
    if not callback:
        return
    callback(
        {
            "source": source,
            "label": label,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
        }
    )
