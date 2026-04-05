from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.agent import OrchestrationRequest
from app.services.agents.orchestration import orchestrate_agents
from app.services.agents.proposal_agent import generate_proposal_draft

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/opportunities/{opportunity_id}/proposal-draft")
def proposal_draft(opportunity_id: int, db: Session = Depends(get_db)):
    try:
        return generate_proposal_draft(opportunity_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/orchestrate")
def orchestrate(request: OrchestrationRequest, db: Session = Depends(get_db)):
    run_ids = orchestrate_agents(request, db)
    return {"run_ids": run_ids}
