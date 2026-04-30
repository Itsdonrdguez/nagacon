from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.pipeline_item import PipelineItem
from app.repositories.opportunities import OpportunityRepository
from app.schemas.opportunity import IngestResult, OpportunityCreate, OpportunityRead, OpportunityUpdate, RawOpportunity
from app.services.search_jobs import start_search_job
from app.services.opportunities.ingest import ingest_raw_opportunities

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


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
