from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.deps import get_current_organization, get_current_user
from app.services.search_jobs import get_search_job, start_search_job

router = APIRouter(prefix="/api/search-jobs", tags=["search-jobs"])


@router.post("")
def create_search_job(
    payload: dict = Body(default={}),
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
    return start_search_job(kind, payload)


@router.get("/{job_id}")
def read_search_job(job_id: str, current_org=Depends(get_current_organization), current_user=Depends(get_current_user)):
    job = get_search_job(job_id)
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
