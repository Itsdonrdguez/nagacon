from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VendorMatchCreate(BaseModel):
    vendor_id: int
    opportunity_id: int
    match_reason: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    source: Optional[str] = "rule_based"


class VendorMatchUpdate(BaseModel):
    match_reason: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    source: Optional[str] = None


class VendorMatchOut(BaseModel):
    id: int
    vendor_id: int
    opportunity_id: int
    vendor_name: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    match_reason: Optional[str] = None
    confidence_score: Optional[float] = None
    source: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
