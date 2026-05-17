from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.pipeline_item import PipelineItem
from app.models.search_job import SearchJob
from app.repositories.opportunities import OpportunityRepository
from app.schemas.opportunity import IngestResult, OpportunityCreate, OpportunityRead, OpportunityUpdate, RawOpportunity
from app.services.search_jobs import start_search_job
from app.services.opportunities.ingest import ingest_raw_opportunities

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _parse_code_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _opportunity_repo(db: Session, organization_id: int | None):
    try:
        return OpportunityRepository(db, organization_id=organization_id)
    except TypeError:
        return OpportunityRepository(db)


def _serialize_opportunities_with_pipeline(db: Session, items: list, organization_id: int | None):
    opp_ids = [getattr(item, "id", None) for item in items if getattr(item, "id", None) is not None]
    pipeline_lookup = {}
    if opp_ids:
        query = db.query(PipelineItem).filter(PipelineItem.opportunity_id.in_(opp_ids))
        if organization_id is not None:
            query = query.filter(PipelineItem.organization_id == organization_id)
        pipeline_lookup = {row.opportunity_id: row for row in query.all()}

    payload = []
    for item in items:
        serialized = OpportunityRead.model_validate(item).model_dump()
        pipeline = pipeline_lookup.get(getattr(item, "id", None))
        if pipeline:
            serialized["decision_status"] = getattr(getattr(pipeline, "decision_status", None), "value", pipeline.decision_status)
            serialized["pipeline_owner"] = getattr(pipeline, "owner", None)
            serialized["target_submit_date"] = pipeline.target_submit_date.isoformat() if getattr(pipeline, "target_submit_date", None) else None
        payload.append(serialized)
    return payload


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    limit: int = 100,
    offset: int = 0,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    agency: str | None = None,
    state: str | None = None,
    naics_codes: str | None = None,
    fsc_codes: str | None = None,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    org_id = getattr(current_org, "id", None)
    items = _opportunity_repo(db, org_id).list(
        limit=limit,
        offset=offset,
        q=q,
        source=source,
        set_aside_type=set_aside_type,
        due_window=due_window,
        nsn=nsn,
        agency=agency,
        state=state,
        naics_codes=_parse_code_list(naics_codes),
        fsc_codes=_parse_code_list(fsc_codes),
    )
    return _serialize_opportunities_with_pipeline(db, items, org_id)


@router.get("/search")
def search_opportunities(
    page: int = 1,
    page_size: int = 25,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    agency: str | None = None,
    state: str | None = None,
    naics_codes: str | None = None,
    fsc_codes: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    org_id = getattr(current_org, "id", None)
    items, total = _opportunity_repo(db, org_id).search(
        page=page,
        page_size=page_size,
        q=q,
        source=source,
        set_aside_type=set_aside_type,
        due_window=due_window,
        nsn=nsn,
        agency=agency,
        state=state,
        naics_codes=_parse_code_list(naics_codes),
        fsc_codes=_parse_code_list(fsc_codes),
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {
        "items": _serialize_opportunities_with_pipeline(db, items, org_id),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/filters")
def opportunity_filter_options(db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return _opportunity_repo(db, getattr(current_org, "id", None)).filter_options()


@router.post("/bulk/workspace-intake")
def bulk_prepare_workspace(
    payload: dict,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    org_id = getattr(current_org, "id", None)
    user_id = getattr(current_user, "id", None)
    raw_ids = payload.get("opportunity_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="opportunity_ids is required")

    seen: set[int] = set()
    opportunity_ids: list[int] = []
    for raw_id in raw_ids[:100]:
        try:
            clean_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if clean_id in seen:
            continue
        seen.add(clean_id)
        opportunity_ids.append(clean_id)

    if not opportunity_ids:
        raise HTTPException(status_code=400, detail="No valid opportunity ids were provided")

    repo = _opportunity_repo(db, org_id)
    opps = [repo.get(opportunity_id) for opportunity_id in opportunity_ids]
    missing = [opportunity_ids[index] for index, opp in enumerate(opps) if not opp]
    if missing:
        raise HTTPException(status_code=404, detail=f"Opportunity not found: {missing[0]}")

    active_jobs = (
        db.query(SearchJob)
        .filter(
            SearchJob.kind == "workspace_intake",
            SearchJob.status.in_(("queued", "running")),
            SearchJob.organization_id == org_id if org_id is not None else SearchJob.organization_id.is_(None),
        )
        .all()
    )
    active_ids = {
        int((job.payload or {}).get("opportunity_id"))
        for job in active_jobs
        if isinstance(job.payload, dict) and (job.payload or {}).get("opportunity_id") is not None
    }

    download_documents = bool(payload.get("download_documents", True))
    run_usaspending = bool(payload.get("run_usaspending", True))

    queued_jobs: list[dict[str, object]] = []
    skipped_duplicates: list[int] = []
    archived_skips: list[int] = []
    for opp in opps:
        if getattr(opp, "opportunity_lifecycle", None) == "ARCHIVED":
            archived_skips.append(int(opp.id))
            continue
        if int(opp.id) in active_ids:
            skipped_duplicates.append(int(opp.id))
            continue
        job = start_search_job(
            "workspace_intake",
            {
                "opportunity_id": int(opp.id),
                "organization_id": org_id,
                "user_id": user_id,
                "download_documents": download_documents,
                "run_usaspending": run_usaspending,
            },
        )
        queued_jobs.append(
            {
                "opportunity_id": int(opp.id),
                "job_id": job.get("id"),
                "status": job.get("status"),
                "title": getattr(opp, "display_title", None) or getattr(opp, "title", None),
            }
        )

    return {
        "status": "ok",
        "requested_count": len(opportunity_ids),
        "queued_count": len(queued_jobs),
        "queued_jobs": queued_jobs,
        "skipped_duplicate_count": len(skipped_duplicates),
        "skipped_duplicate_opportunity_ids": skipped_duplicates,
        "archived_skip_count": len(archived_skips),
        "archived_skip_opportunity_ids": archived_skips,
    }


@router.post("/{opportunity_id}/awardee-enrichment-job")
def start_awardee_enrichment_job(
    opportunity_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    org_id = getattr(current_org, "id", None)
    opp = _opportunity_repo(db, org_id).get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return start_search_job(
        "awardee_enrichment",
        {
            "opportunity_id": opportunity_id,
            "organization_id": org_id,
            "user_id": getattr(current_user, "id", None),
            "force": force,
        },
    )


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    org_id = getattr(current_org, "id", None)
    opp = _opportunity_repo(db, org_id).get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return _serialize_opportunities_with_pipeline(db, [opp], org_id)[0]


@router.post("", response_model=OpportunityRead)
def create_opportunity(payload: OpportunityCreate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return _opportunity_repo(db, getattr(current_org, "id", None)).create(payload)


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(opportunity_id: int, payload: OpportunityUpdate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    updated = _opportunity_repo(db, getattr(current_org, "id", None)).update(opportunity_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return updated


@router.post("/ingest", response_model=IngestResult)
def ingest_opportunities(raw_records: list[RawOpportunity], db: Session = Depends(get_db)):
    return ingest_raw_opportunities(db, raw_records)
