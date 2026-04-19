from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.repositories.pipeline import PipelineRepository
from app.schemas.pipeline import PipelineItemCreate, PipelineItemOut, PipelineItemUpdate
from app.services.pipeline.decision import create_or_get_pipeline, update_pipeline_item

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _pipeline_repo(db: Session, organization_id: int | None):
    try:
        return PipelineRepository(db, organization_id=organization_id)
    except TypeError:
        return PipelineRepository(db)


@router.get("/board")
def list_pipeline_board(
    q: str | None = None,
    source: str | None = None,
    status: str | None = None,
    include_closed: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    items = _pipeline_repo(db, getattr(current_org, "id", None)).list_board(
        q=q,
        source=source,
        status=status,
        include_closed=include_closed,
        limit=limit,
    )
    summary = {}
    for item in items:
        key = item["decision_status"]
        summary[key] = summary.get(key, 0) + 1
    return {
        "items": items,
        "summary": summary,
        "total": len(items),
    }


@router.get("/{pipeline_id}", response_model=PipelineItemOut)
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    item = _pipeline_repo(db, getattr(current_org, "id", None)).get(pipeline_id)
    if not item:
        raise HTTPException(status_code=404, detail="Pipeline item not found")
    return item


@router.get("/by-opportunity/{opportunity_id}", response_model=PipelineItemOut | None)
def get_pipeline_by_opportunity(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return _pipeline_repo(db, getattr(current_org, "id", None)).get_by_opportunity_id(opportunity_id)


@router.post("/by-opportunity/{opportunity_id}", response_model=PipelineItemOut)
def create_or_get_pipeline_route(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return create_or_get_pipeline(opportunity_id, db, organization_id=getattr(current_org, "id", None))


@router.post("/", response_model=PipelineItemOut)
def create_pipeline(item: PipelineItemCreate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    existing = _pipeline_repo(db, getattr(current_org, "id", None)).get_by_opportunity_id(item.opportunity_id)
    if existing:
        return existing
    return _pipeline_repo(db, getattr(current_org, "id", None)).create(item)


@router.patch("/{pipeline_id}", response_model=PipelineItemOut)
def update_pipeline(pipeline_id: int, item_update: PipelineItemUpdate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    updated = update_pipeline_item(
        pipeline_id,
        decision_status=item_update.decision_status,
        owner=item_update.owner,
        priority=item_update.priority,
        probability_of_win=item_update.probability_of_win,
        notes=item_update.notes,
        target_submit_date=item_update.target_submit_date,
        db=db,
        organization_id=getattr(current_org, "id", None),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Pipeline item not found")
    return updated
