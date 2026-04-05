from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.agent_run import AgentType


class AgentRunBase(BaseModel):
    opportunity_id: Optional[int] = None
    agent_type: AgentType
    input_payload: Optional[Dict[str, Any]] = None
    output_payload: Optional[Dict[str, Any]] = None
    status: str = "pending"
    model_name: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AgentRunCreate(AgentRunBase):
    pass


class AgentRunUpdate(BaseModel):
    output_payload: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    model_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AgentRunOut(AgentRunBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class OrchestrationRequest(BaseModel):
    opportunity_id: int
    agents: List[AgentType] = Field(default_factory=list)
