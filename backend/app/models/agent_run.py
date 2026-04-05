from __future__ import annotations

from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.db import Base


class AgentType(str, Enum):
    OPPORTUNITY_ANALYZER = "opportunity_analyzer"
    VENDOR_DISCOVERY = "vendor_discovery"
    PRICING = "pricing"
    PROPOSAL = "proposal"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True, index=True)
    agent_type = Column(SQLEnum(AgentType, name="agent_type"), nullable=False)
    input_payload = Column(JSONB, nullable=True)
    output_payload = Column(JSONB, nullable=True)
    status = Column(String, nullable=False, default="pending")
    model_name = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
