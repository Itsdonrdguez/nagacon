from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    artifact_type: str
    title: str
    content_json: Optional[dict[str, Any]] = None
    file_path: Optional[str] = None
    created_at: datetime

class TaskCreate(BaseModel):
    task_type: str = "FOLLOW_UP"
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


class TaskUpdate(BaseModel):
    task_type: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    task_type: str
    status: str
    due_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

class GenerateIn(BaseModel):
    opportunity_id: int


class ArtifactUpdate(BaseModel):
    title: Optional[str] = None
    content_json: Optional[dict[str, Any]] = None
