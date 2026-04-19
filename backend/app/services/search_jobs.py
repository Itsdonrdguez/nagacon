from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.api.scrapers import run_multi_source_search
from app.core.db import SessionLocal
from app.models.search_job import SearchJob
from app.repositories.company import CompanyRepository
from app.services.company_profile_ingest import run_company_profile_ingest
from app.services.dibbs.pdf_bulk_export import export_dibbs_pdfs_for_fscs
from app.services.opportunity_intake_pipeline import run_opportunity_intake_pipeline

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


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
        "status": job["status"],
        "progress": dict(job.get("progress") or {}),
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
        "status": row.status,
        "progress": dict(row.progress or {}),
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
            )
        elif kind == "manual":
            result = run_multi_source_search(
                payload.get("search") or {},
                db,
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


def start_search_job(kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    payload = dict(payload or {})
    job = {
        "id": job_id,
        "kind": kind,
        "organization_id": payload.get("organization_id"),
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
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, kind, payload),
        daemon=True,
        name=f"nagacon-search-{job_id[:8]}",
    )
    thread.start()
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
