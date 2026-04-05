from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.core.db import Base
from app.utils.enums import PipelineStatus


class PipelineItem(Base):
    __tablename__ = "pipeline_items"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False, unique=True, index=True)
    decision_status = Column(
        SQLEnum(PipelineStatus, name="pipeline_status"),
        nullable=False,
        default=PipelineStatus.NEW,
    )
    owner = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    probability_of_win = Column(Float, nullable=True)  # 0-100
    notes = Column(Text, nullable=True)
    target_submit_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
