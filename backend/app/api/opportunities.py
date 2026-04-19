from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
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


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    limit: int = 100,
    offset: int = 0,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return _opportunity_repo(db, getattr(current_org, "id", None)).list(
        limit=limit,
        offset=offset,
        q=q,
        source=source,
        set_aside_type=set_aside_type,
        due_window=due_window,
        nsn=nsn,
    )


@router.get("/search")
def search_opportunities(
    page: int = 1,
    page_size: int = 25,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
    nsn: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    items, total = _opportunity_repo(db, getattr(current_org, "id", None)).search(
        page=page,
        page_size=page_size,
        q=q,
        source=source,
        set_aside_type=set_aside_type,
        due_window=due_window,
        nsn=nsn,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {
        "items": [OpportunityRead.model_validate(item).model_dump() for item in items],
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
            "force": force,
        },
    )


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp = _opportunity_repo(db, getattr(current_org, "id", None)).get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp


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
