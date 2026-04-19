from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.pipeline_item import PipelineItem
from app.schemas.pipeline import PipelineItemCreate, PipelineItemUpdate
from app.utils.enums import PipelineStatus
from app.utils.solicitation_status import derive_solicitation_status


class PipelineRepository:
    def __init__(self, db: Session, organization_id: int | None = None):
        self.db = db
        self.organization_id = organization_id

    def _scoped_pipeline_query(self):
        query = self.db.query(PipelineItem)
        if self.organization_id is not None:
            query = query.filter(PipelineItem.organization_id == self.organization_id)
        return query

    def get(self, pipeline_id: int):
        try:
            return self._scoped_pipeline_query().filter(PipelineItem.id == pipeline_id).first()
        except Exception:
            self.db.rollback()
            return None

    def get_by_opportunity_id(self, opportunity_id: int):
        try:
            return (
                self._scoped_pipeline_query()
                .filter(PipelineItem.opportunity_id == opportunity_id)
                .first()
            )
        except Exception:
            self.db.rollback()
            return None

    def create(self, item: PipelineItemCreate):
        rec = PipelineItem(
            organization_id=self.organization_id,
            opportunity_id=item.opportunity_id,
            decision_status=item.decision_status,
            owner=item.owner,
            priority=item.priority,
            probability_of_win=item.probability_of_win,
            notes=item.notes,
            target_submit_date=item.target_submit_date,
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def create_or_get(self, opportunity_id: int):
        existing = self.get_by_opportunity_id(opportunity_id)
        if existing:
            return existing
        return self.create(
            PipelineItemCreate(
                opportunity_id=opportunity_id,
                decision_status=PipelineStatus.NEW,
            )
        )

    def update(self, pipeline_id: int, item_update: PipelineItemUpdate):
        rec = self.get(pipeline_id)
        if not rec:
            return None

        payload = item_update.model_dump(exclude_unset=True)
        for key, value in payload.items():
            setattr(rec, key, value)

        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def list_board(
        self,
        *,
        q: str | None = None,
        source: str | None = None,
        status: PipelineStatus | str | None = None,
        include_closed: bool = False,
        limit: int = 100,
    ):
        query = (
            self.db.query(PipelineItem, Opportunity)
            .join(Opportunity, Opportunity.id == PipelineItem.opportunity_id)
            .order_by(PipelineItem.updated_at.desc())
        )
        if self.organization_id is not None:
            query = query.filter(PipelineItem.organization_id == self.organization_id, Opportunity.organization_id == self.organization_id)

        if source:
            query = query.filter(Opportunity.source == source)

        if status:
            status_value = status.value if hasattr(status, "value") else status
            query = query.filter(PipelineItem.decision_status == status_value)

        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Opportunity.title.ilike(pattern),
                    Opportunity.agency.ilike(pattern),
                    Opportunity.solicitation_number.ilike(pattern),
                    PipelineItem.owner.ilike(pattern),
                )
            )

        rows = query.limit(limit).all()
        items = []
        for pipeline_item, opportunity in rows:
            solicitation_status = derive_solicitation_status(opportunity.due_at)
            if not include_closed and solicitation_status == "CLOSED":
                continue
            items.append(
                {
                    "id": pipeline_item.id,
                    "opportunity_id": pipeline_item.opportunity_id,
                    "decision_status": getattr(getattr(pipeline_item, "decision_status", None), "value", pipeline_item.decision_status),
                    "owner": pipeline_item.owner,
                    "priority": pipeline_item.priority,
                    "probability_of_win": pipeline_item.probability_of_win,
                    "target_submit_date": pipeline_item.target_submit_date.isoformat() if pipeline_item.target_submit_date else None,
                    "updated_at": pipeline_item.updated_at.isoformat() if pipeline_item.updated_at else None,
                    "opportunity": {
                        "id": opportunity.id,
                        "title": opportunity.title,
                        "display_title": getattr(opportunity, "display_title", opportunity.title),
                        "agency": opportunity.agency,
                        "source": opportunity.source,
                        "solicitation_number": opportunity.solicitation_number,
                        "due_at": opportunity.due_at.isoformat() if opportunity.due_at else None,
                        "set_aside_type": getattr(opportunity, "set_aside", None),
                        "solicitation_status": solicitation_status,
                    },
                }
            )
        return items
