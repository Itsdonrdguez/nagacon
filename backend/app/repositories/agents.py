from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.schemas.agent import AgentRunCreate, AgentRunUpdate


class AgentRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, run_id: int) -> Optional[AgentRun]:
        return self.db.query(AgentRun).filter(AgentRun.id == run_id).first()

    def create(self, item: AgentRunCreate) -> AgentRun:
        rec = AgentRun(**item.model_dump())
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def list_by_opportunity_id(self, opportunity_id: int) -> List[AgentRun]:
        return (
            self.db.query(AgentRun)
            .filter(AgentRun.opportunity_id == opportunity_id)
            .order_by(AgentRun.created_at.desc())
            .all()
        )

    def update(self, run_id: int, item: AgentRunUpdate) -> Optional[AgentRun]:
        rec = self.get(run_id)
        if not rec:
            return None
        for key, value in item.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(rec, key, value)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def update_status(
        self,
        run_id: int,
        status: str,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[AgentRun]:
        payload = AgentRunUpdate(
            status=status,
            output_payload=output,
            error_message=error,
            completed_at=datetime.now(timezone.utc) if status in {"success", "failed"} else None,
        )
        return self.update(run_id, payload)
