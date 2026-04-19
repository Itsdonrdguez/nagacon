from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.deps import get_current_organization
from app.services.search_jobs import get_search_job, start_search_job

router = APIRouter(prefix="/api/search-jobs", tags=["search-jobs"])


@router.post("")
def create_search_job(payload: dict = Body(default={}), current_org=Depends(get_current_organization)):
    payload = dict(payload or {})
    payload.setdefault("organization_id", getattr(current_org, "id", None))
    kind = str(payload.get("kind") or "manual").strip().lower()
    if kind not in {"profile", "manual", "dibbs_pdf_bulk_download", "workspace_intake"}:
        raise HTTPException(status_code=400, detail="Search job kind must be profile, manual, dibbs_pdf_bulk_download, or workspace_intake")
    return start_search_job(kind, payload)


@router.get("/{job_id}")
def read_search_job(job_id: str):
    job = get_search_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Search job not found")
    return job
