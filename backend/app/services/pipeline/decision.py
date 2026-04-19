from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.repositories.pipeline import PipelineRepository
from app.schemas.pipeline import PipelineItemOut, PipelineItemUpdate
from app.utils.enums import PipelineStatus

def create_or_get_pipeline(opportunity_id: int, db: Session, organization_id: int | None = None):
    try:
        repo = PipelineRepository(db, organization_id=organization_id)
    except TypeError:
        repo = PipelineRepository(db)
    return repo.create_or_get(opportunity_id)


def update_pipeline_item(
    pipeline_id: int,
    *,
    decision_status: Optional[PipelineStatus] = None,
    owner: Optional[str] = None,
    priority: Optional[str] = None,
    probability_of_win: Optional[float] = None,
    notes: Optional[str] = None,
    target_submit_date=None,
    db: Session,
    organization_id: int | None = None,
):
    try:
        repo = PipelineRepository(db, organization_id=organization_id)
    except TypeError:
        repo = PipelineRepository(db)

    payload = PipelineItemUpdate(
        decision_status=decision_status,
        owner=owner,
        priority=priority,
        probability_of_win=probability_of_win,
        notes=notes,
        target_submit_date=target_submit_date,
    )
    return repo.update(pipeline_id, payload)
