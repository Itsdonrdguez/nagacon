from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.search_jobs import SearchJobLookupUnavailable, get_search_job, recover_stale_jobs_now, start_search_job
from app.services.work_queue import workspace_intake_backpressure_snapshot

router = APIRouter(prefix="/api/search-jobs", tags=["search-jobs"])


@router.post("")
def create_search_job(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    payload = dict(payload or {})
    payload.setdefault("organization_id", getattr(current_org, "id", None))
    payload.setdefault("user_id", getattr(current_user, "id", None))
    kind = str(payload.get("kind") or "manual").strip().lower()
    allowed = {"profile", "manual", "dibbs_pdf_bulk_download", "workspace_intake", "nsn_build", "awardee_enrichment", "publog_sync", "provider_backfill"}
    if kind not in allowed:
        raise HTTPException(status_code=400, detail=f"Search job kind must be one of: {', '.join(sorted(allowed))}")
    if kind == "workspace_intake":
        backpressure = workspace_intake_backpressure_snapshot(db, getattr(current_org, "id", None))
        if backpressure.get("blocked"):
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "workspace_intake queue is at capacity",
                    "workspace_intake_backpressure": backpressure,
                },
            )
    return start_search_job(kind, payload)


@router.get("/{job_id}")
def read_search_job(job_id: str, current_org=Depends(get_current_organization), current_user=Depends(get_current_user)):
    try:
        job = get_search_job(job_id)
    except SearchJobLookupUnavailable:
        raise HTTPException(status_code=503, detail="Search job status temporarily unavailable")
    if not job:
        raise HTTPException(status_code=404, detail="Search job not found")
    job_org = (job.get("result") or {}).get("organization_id") or (job.get("payload") or {}).get("organization_id")
    current_org_id = getattr(current_org, "id", None)
    if job_org is not None and current_org_id is not None and int(job_org) != int(current_org_id):
        raise HTTPException(status_code=404, detail="Search job not found")
    job_user = job.get("user_id") or (job.get("result") or {}).get("user_id") or (job.get("payload") or {}).get("user_id")
    current_user_id = getattr(current_user, "id", None)
    if job_user is not None and current_user_id is not None and int(job_user) != int(current_user_id):
        raise HTTPException(status_code=404, detail="Search job not found")
    return job


@router.post("/recover-stale")
def recover_stale_jobs(
    payload: dict = Body(default={}),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    limit = payload.get("limit")
    try:
        limit_value = int(limit) if limit is not None else None
    except Exception:
        raise HTTPException(status_code=400, detail="limit must be an integer")
    result = recover_stale_jobs_now(limit=limit_value)
    return {
        **result,
        "organization_id": getattr(current_org, "id", None),
        "user_id": getattr(current_user, "id", None),
    }
