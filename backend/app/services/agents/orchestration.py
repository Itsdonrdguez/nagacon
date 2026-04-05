from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.agent_run import AgentType
from app.repositories.agents import AgentRunRepository
from app.schemas.agent import AgentRunCreate, OrchestrationRequest


def _run_opportunity_analyzer(opportunity_id: int, db: Session) -> Dict[str, Any]:
    # Replace this import with your real analyzer service when ready.
    from app.services.opportunities.query import get_opportunity_workspace

    workspace = get_opportunity_workspace(opportunity_id, db)
    if not workspace:
        raise ValueError("Workspace not found")

    opp = workspace.get("opportunity") or {}
    return {
        "summary": {
            "title": opp.get("title"),
            "agency": opp.get("agency"),
            "solicitation_number": opp.get("solicitation_number"),
        },
        "notes": "Basic analyzer stub. Replace with full opportunity analysis service.",
    }


def _run_vendor_discovery(opportunity_id: int, db: Session) -> Dict[str, Any]:
    from app.services.vendors.discovery import discover_vendors_for_opportunity

    return discover_vendors_for_opportunity(opportunity_id, db)


def _run_pricing(opportunity_id: int, db: Session) -> Dict[str, Any]:
    from app.repositories.quotes import QuoteRepository

    quotes = QuoteRepository(db).list_by_opportunity_id(opportunity_id)
    total = sum(float(q.total_price or 0) for q in quotes)
    return {
        "quote_count": len(quotes),
        "total_quote_value": round(total, 2),
    }


def _run_proposal(opportunity_id: int, db: Session) -> Dict[str, Any]:
    from app.services.agents.proposal_agent import generate_proposal_draft

    return generate_proposal_draft(opportunity_id, db)


def _dispatch(agent_type: AgentType, opportunity_id: int, db: Session) -> Dict[str, Any]:
    if agent_type == AgentType.OPPORTUNITY_ANALYZER:
        return _run_opportunity_analyzer(opportunity_id, db)
    if agent_type == AgentType.VENDOR_DISCOVERY:
        return _run_vendor_discovery(opportunity_id, db)
    if agent_type == AgentType.PRICING:
        return _run_pricing(opportunity_id, db)
    if agent_type == AgentType.PROPOSAL:
        return _run_proposal(opportunity_id, db)
    raise ValueError(f"Unsupported agent type: {agent_type}")


def orchestrate_agents(request: OrchestrationRequest, db: Session) -> List[int]:
    repo = AgentRunRepository(db)
    run_ids: List[int] = []

    for agent_type in request.agents:
        run = repo.create(
            AgentRunCreate(
                opportunity_id=request.opportunity_id,
                agent_type=agent_type,
                input_payload={"opportunity_id": request.opportunity_id},
                status="running",
                model_name="orchestrated",
                started_at=datetime.now(timezone.utc),
            )
        )
        run_ids.append(run.id)

        try:
            output = _dispatch(agent_type, request.opportunity_id, db)
            repo.update_status(run.id, "success", output=output)
        except Exception as exc:
            repo.update_status(run.id, "failed", error=str(exc))

    return run_ids
