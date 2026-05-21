from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.workflow_event import OpportunityWorkflowEvent


def record_workflow_event(
    db: Session,
    *,
    opportunity_id: int,
    action: str,
    entity_type: str,
    organization_id: int | None = None,
    user_id: int | None = None,
    entity_id: int | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    notes: str | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> OpportunityWorkflowEvent:
    rec = OpportunityWorkflowEvent(
        organization_id=organization_id,
        opportunity_id=opportunity_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        from_state=from_state,
        to_state=to_state,
        notes=notes,
        metadata_json=metadata or None,
    )
    db.add(rec)
    if commit:
        db.commit()
        db.refresh(rec)
    return rec
