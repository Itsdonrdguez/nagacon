from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.utils.enums import PipelineStatus


class PipelineItemBase(BaseModel):
    opportunity_id: int
    decision_status: PipelineStatus = PipelineStatus.NEW
    owner: Optional[str] = None
    priority: Optional[str] = None
    probability_of_win: Optional[float] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None
    target_submit_date: Optional[datetime] = None


class PipelineItemCreate(PipelineItemBase):
    pass


class PipelineItemUpdate(BaseModel):
    decision_status: Optional[PipelineStatus] = None
    owner: Optional[str] = None
    priority: Optional[str] = None
    probability_of_win: Optional[float] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None
    target_submit_date: Optional[datetime] = None


class PipelineItemOut(PipelineItemBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
