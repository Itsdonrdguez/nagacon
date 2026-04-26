from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.api.scrapers import run_multi_source_search
from app.core.config import settings
from app.core.db import SessionLocal
from app.models.search_job import SearchJob
from app.repositories.company import CompanyRepository
from app.services.awardee_enrichment import enrich_awardees_for_opportunity
from app.services.company_profile_ingest import run_company_profile_ingest
from app.services.dibbs.pdf_bulk_export import export_dibbs_pdfs_for_fscs
from app.services.nsn_catalog.build import build_nsn_intelligence
from app.services.nsn_catalog.publog_sync import sync_publog_package
from app.services.opportunity_intake_pipeline import run_opportunity_intake_pipeline
from app.services.providers.provider_backfill import run_provider_backfill

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _runner_mode() -> str:
    return str(getattr(settings, "SEARCH_JOB_RUNNER", "thread") or "thread").strip().lower()


def uses_external_worker() -> bool:
    return _runner_mode() in {"worker", "external_worker", "db_worker"}


def _max_concurrency() -> int:
    try:
        return max(1, int(getattr(settings, "SEARCH_JOB_MAX_CONCURRENCY", 4) or 4))
    except Exception:
        return 4


def _thread_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=_max_concurrency(), thread_name_prefix="nagacon-search")
        return _executor


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "kind": job["kind"],
        "user_id": job.get("user_id"),
        "status": job["status"],
        "progress": dict(job.get("progress") or {}),
        "payload": job.get("payload"),
        "result": job.get("result"),
        "error": job.get("error"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "events": list(job.get("events") or [])[-20:],
    }


def _db_snapshot(row: SearchJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "user_id": row.user_id,
        "status": row.status,
        "progress": dict(row.progress or {}),
        "payload": row.payload,
        "result": row.result,
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "events": list(row.events or [])[-20:],
    }


def _persist_job(job: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        row = db.get(SearchJob, job["id"])
        if not row:
            row = SearchJob(id=job["id"], kind=job["kind"])
        row.organization_id = job.get("organization_id")
        row.user_id = job.get("user_id")
        row.kind = job["kind"]
        row.status = job["status"]
        row.payload = _json_safe(job.get("payload"))
        row.progress = _json_safe(dict(job.get("progress") or {}))
        row.result = _json_safe(job.get("result"))
        row.events = _json_safe(list(job.get("events") or []))
        row.error = job.get("error")
        row.started_at = _parse_dt(job.get("started_at"))
        row.completed_at = _parse_dt(job.get("completed_at"))
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _update_job(job_id: str, **updates: Any) -> None:
    snapshot = None
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(updates)
        snapshot = dict(job)
    if snapshot:
        _persist_job(snapshot)


def _append_progress(job_id: str, event: dict[str, Any]) -> None:
    snapshot = None
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        completed = int(event.get("completed_steps") or 0)
        total = int(event.get("total_steps") or 0)
        percent = int((completed / total) * 100) if total else 0
        job["progress"] = {
            "completed_steps": completed,
            "total_steps": total,
            "percent": min(max(percent, 0), 100),
            "current_source": event.get("source"),
            "current_label": event.get("label"),
            "last_raw_rows": event.get("raw_rows"),
        }
        job.setdefault("events", []).append(
            {
                "timestamp": _now(),
                "source": event.get("source"),
                "label": event.get("label"),
                "raw_rows": event.get("raw_rows"),
                "completed_steps": completed,
                "total_steps": total,
            }
        )
        snapshot = dict(job)
    if snapshot:
        _persist_job(snapshot)


def _run_job(job_id: str, kind: str, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        _update_job(job_id, status="running", started_at=_now())
        if kind == "profile":
            profile = CompanyRepository(db).get_first_profile()
            if not profile:
                raise ValueError("Company profile not found")
            result = run_company_profile_ingest(
                db,
                profile,
                quick=bool(payload.get("quick", True)),
                update_last_run=not bool(payload.get("quick", True)),
                progress_callback=lambda event: _append_progress(job_id, event),
                user_id=payload.get("user_id"),
            )
        elif kind == "manual":
            result = run_multi_source_search(
                payload.get("search") or {},
                db,
                user_id=payload.get("user_id"),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "dibbs_pdf_bulk_download":
            profile = CompanyRepository(db).get_first_profile()
            if not profile:
                raise ValueError("Company profile not found")
            fscs = payload.get("fscs") or payload.get("q") or getattr(profile, "preferred_dibbs_fsc_codes", None) or []
            if isinstance(fscs, str):
                fscs = [item.strip() for item in fscs.split(",") if item.strip()]
            limit = int(
                payload.get("limit")
                or getattr(profile, "dibbs_pdf_download_limit", None)
                or 25
            )
            result = export_dibbs_pdfs_for_fscs(
                fscs=fscs,
                limit_per_fsc=limit,
                include_past_due=bool(payload.get("include_past_due", False)),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "workspace_intake":
            opportunity_id = int(payload.get("opportunity_id") or payload.get("opp_id") or 0)
            if not opportunity_id:
                raise ValueError("opportunity_id is required for workspace_intake jobs")
            result = run_opportunity_intake_pipeline(
                db,
                opportunity_id,
                organization_id=payload.get("organization_id"),
                download_documents=bool(payload.get("download_documents", True)),
                run_usaspending=bool(payload.get("run_usaspending", True)),
                user_id=payload.get("user_id"),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "nsn_build":
            nsn = str(payload.get("nsn") or "").strip()
            if not nsn:
                raise ValueError("nsn is required for nsn_build jobs")
            result = build_nsn_intelligence(
                db,
                nsn,
                seed_providers=bool(payload.get("seed_providers", True)),
                run_usaspending=bool(payload.get("run_usaspending", True)),
                limit=int(payload.get("limit") or 50),
                organization_id=payload.get("organization_id"),
                user_id=payload.get("user_id"),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "publog_sync":
            result = sync_publog_package(
                db,
                zip_path=payload.get("zip_path"),
                publog_dir=payload.get("publog_dir"),
                source_version=payload.get("source_version"),
                nsns=payload.get("nsns"),
                target_limit=int(payload.get("target_limit") or 250),
                dry_run=bool(payload.get("dry_run", False)),
                force=bool(payload.get("force", False)),
                compute_hash=bool(payload.get("compute_hash", False)),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "awardee_enrichment":
            opportunity_id = int(payload.get("opportunity_id") or payload.get("opp_id") or 0)
            if not opportunity_id:
                raise ValueError("opportunity_id is required for awardee_enrichment jobs")
            result = enrich_awardees_for_opportunity(
                db,
                opportunity_id,
                organization_id=payload.get("organization_id"),
                force=bool(payload.get("force", False)),
                user_id=payload.get("user_id"),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        elif kind == "provider_backfill":
            result = run_provider_backfill(
                db,
                organization_id=payload.get("organization_id"),
                limit=int(payload.get("limit") or 250),
                enrich_websites=bool(payload.get("enrich_websites", True)),
                user_id=payload.get("user_id"),
                progress_callback=lambda event: _append_progress(job_id, event),
            )
        else:
            raise ValueError(f"Unsupported search job kind: {kind}")
        _update_job(
            job_id,
            status="success",
            result=result,
            completed_at=_now(),
            progress={**(_jobs.get(job_id, {}).get("progress") or {}), "percent": 100},
        )
    except Exception as exc:
        _update_job(job_id, status="failed", error=str(exc), completed_at=_now())
    finally:
        db.close()


def _queued_job_query(db):
    return db.query(SearchJob).filter(SearchJob.status == "queued").order_by(SearchJob.created_at.asc(), SearchJob.id.asc())


def claim_next_queued_job() -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        while True:
            row = _queued_job_query(db).first()
            if not row:
                return None
            started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            updated = (
                db.query(SearchJob)
                .filter(SearchJob.id == row.id, SearchJob.status == "queued")
                .update(
                    {
                        SearchJob.status: "running",
                        SearchJob.started_at: started_at,
                        SearchJob.error: None,
                    },
                    synchronize_session=False,
                )
            )
            if updated:
                db.commit()
                db.refresh(row)
                snapshot = _db_snapshot(row)
                with _lock:
                    _jobs[row.id] = {
                        "id": row.id,
                        "kind": row.kind,
                        "organization_id": row.organization_id,
                        "user_id": row.user_id,
                        "status": row.status,
                        "progress": dict(row.progress or {"completed_steps": 0, "total_steps": 0, "percent": 0}),
                        "payload": dict(row.payload or {}),
                        "result": row.result,
                        "error": row.error,
                        "started_at": snapshot.get("started_at"),
                        "completed_at": snapshot.get("completed_at"),
                        "events": list(row.events or []),
                    }
                return snapshot
            db.rollback()
    finally:
        db.close()


def run_claimed_job(job_id: str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        row = db.get(SearchJob, job_id)
        if not row:
            return None
        payload = dict(row.payload or {})
        kind = row.kind
    finally:
        db.close()
    _run_job(job_id, kind, payload)
    return get_search_job(job_id)


def run_one_queued_job() -> dict[str, Any] | None:
    claimed = claim_next_queued_job()
    if not claimed:
        return None
    return run_claimed_job(claimed["id"])


def start_search_job(kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    payload = dict(payload or {})
    job = {
        "id": job_id,
        "kind": kind,
        "organization_id": payload.get("organization_id"),
        "user_id": payload.get("user_id"),
        "status": "queued",
        "progress": {"completed_steps": 0, "total_steps": 0, "percent": 0},
        "payload": payload,
        "result": None,
        "error": None,
        "started_at": None,
        "completed_at": None,
        "events": [],
    }
    with _lock:
        _jobs[job_id] = job
    _persist_job(job)
    if uses_external_worker():
        return _snapshot(job)
    _thread_executor().submit(_run_job, job_id, kind, payload)
    return _snapshot(job)


def record_search_job(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    status: str = "success",
    result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    payload = dict(payload or {})
    job = {
        "id": job_id,
        "kind": kind,
        "organization_id": payload.get("organization_id"),
        "user_id": payload.get("user_id"),
        "status": status,
        "progress": dict(progress or {}),
        "payload": payload,
        "result": result,
        "error": error,
        "started_at": _now(),
        "completed_at": _now(),
        "events": [],
    }
    with _lock:
        _jobs[job_id] = job
    _persist_job(job)
    return _snapshot(job)


def get_search_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            return _snapshot(job)
    db = SessionLocal()
    try:
        row = db.get(SearchJob, job_id)
        return _db_snapshot(row) if row else None
    finally:
        db.close()


def worker_loop(*, poll_seconds: float | None = None, max_jobs: int | None = None) -> int:
    delay = float(poll_seconds if poll_seconds is not None else getattr(settings, "SEARCH_JOB_POLL_SECONDS", 2.0))
    processed = 0
    while True:
        result = run_one_queued_job()
        if result:
            processed += 1
            if max_jobs is not None and processed >= max_jobs:
                return processed
            continue
        if max_jobs is not None:
            return processed
        time.sleep(max(delay, 0.25))
