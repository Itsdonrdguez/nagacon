from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class OpportunityFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    file_type: str
    filename: str
    source_url: str | None = None
    file_path: str
    created_at: datetime
    has_extracted_text: bool = False
    has_parsed_metadata: bool = False
    processing_status: str | None = None
    document_type: str | None = None
    review_required: bool = False
    storage_class: str | None = None
    retention_status: str | None = None
    retention_reason: str | None = None
    prune_eligible: bool = False

class OpportunityFileInsightsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int
    file_type: str
    filename: str
    source_url: str | None = None
    created_at: datetime
    has_extracted_text: bool = False
    has_parsed_metadata: bool = False
    extracted_text: str | None = None
    text_preview: str | None = None
    parsed_metadata: dict | None = None
    processing_status: str | None = None
    document_type: str | None = None
    review_required: bool = False
    storage_class: str | None = None
    retention_status: str | None = None
    retention_reason: str | None = None
    prune_eligible: bool = False
