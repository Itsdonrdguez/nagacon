from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class ArtifactOut(BaseModel):
    id: int
    opportunity_id: int
    artifact_type: str
    title: str
    content_json: Optional[dict[str, Any]] = None
    file_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    task_type: str = "FOLLOW_UP"
    due_at: Optional[datetime] = None
    notes: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    opportunity_id: int
    task_type: str
    status: str
    due_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateIn(BaseModel):
    opportunity_id: int
