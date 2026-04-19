from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import workspace as workspace_api
from app.core.deps import get_current_organization, get_db
from app.core.security import require_integration_api_key
from app.repositories.opportunities import OpportunityRepository
from app.repositories.pipeline import PipelineRepository
from app.schemas.opportunity import OpportunityRead


router = APIRouter(
    prefix="/api/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_integration_api_key)],
)


def _opportunity_repo(db: Session, organization_id: int | None):
    try:
        return OpportunityRepository(db, organization_id=organization_id)
    except TypeError:
        return OpportunityRepository(db)


def _pipeline_repo(db: Session, organization_id: int | None):
    try:
        return PipelineRepository(db, organization_id=organization_id)
    except TypeError:
        return PipelineRepository(db)


@router.get("/health")
def integration_health():
    return {
        "status": "ok",
        "auth": "api_key",
        "header": "X-API-Key",
        "available_endpoints": [
            "/api/integrations/opportunities/search",
            "/api/integrations/opportunities/{opportunity_id}",
            "/api/integrations/workspace/{opportunity_id}/summary",
            "/api/integrations/workspace/{opportunity_id}/run-agent",
            "/api/integrations/workspace/{opportunity_id}/run-phase",
            "/api/integrations/workspace/{opportunity_id}/usaspending",
            "/api/integrations/pipeline/board",
        ],
    }


@router.get("/opportunities/search")
def integration_search_opportunities(
    page: int = 1,
    page_size: int = 25,
    q: str | None = None,
    source: str | None = None,
    set_aside_type: str | None = None,
    due_window: str | None = None,
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
    )
    return {
        "items": [OpportunityRead.model_validate(item).model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/opportunities/{opportunity_id}")
def integration_get_opportunity(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    opp = _opportunity_repo(db, getattr(current_org, "id", None)).get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return OpportunityRead.model_validate(opp).model_dump()


@router.get("/workspace/{opportunity_id}/summary")
def integration_workspace_summary(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return workspace_api.workspace_summary(opp_id=opportunity_id, db=db, current_org=current_org)


@router.post("/workspace/{opportunity_id}/run-agent")
def integration_run_workspace_agent(opportunity_id: int, payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    body = dict(payload or {})
    body["opportunity_id"] = opportunity_id
    return workspace_api.run_workspace_agent_route(payload=body, db=db, current_org=current_org)


@router.post("/workspace/{opportunity_id}/run-phase")
def integration_run_workspace_phase(opportunity_id: int, payload: dict, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    body = dict(payload or {})
    body["opportunity_id"] = opportunity_id
    return workspace_api.run_workspace_agent_phase(payload=body, db=db, current_org=current_org)


@router.get("/workspace/{opportunity_id}/usaspending")
def integration_workspace_usaspending(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    return workspace_api.workspace_usaspending_vendors(opp_id=opportunity_id, db=db, current_org=current_org)


@router.get("/pipeline/board")
def integration_pipeline_board(
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
    summary: dict[str, int] = {}
    for item in items:
        key = item["decision_status"]
        summary[key] = summary.get(key, 0) + 1
    return {"items": items, "summary": summary, "total": len(items)}
