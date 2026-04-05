from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class OpportunityFileOut(BaseModel):
    id: int
    opportunity_id: int
    file_type: str
    filename: str
    source_url: str | None = None
    file_path: str
    created_at: datetime

    class Config:
        from_attributes = True
