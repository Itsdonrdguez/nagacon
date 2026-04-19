from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class VendorLeadOut(BaseModel):
    id: int
    opportunity_id: int
    source_type: str
    company_name: str | None = None
    cage: str | None = None
    part_number: str | None = None
    nsn: str | None = None
    status: str
    confidence: int
    is_approved_source: bool
    raw_text: str | None = None
    notes: str | None = None
    source_label: str | None = None
    provider_website: str | None = None
    provider_email: str | None = None
    provider_phone: str | None = None
    provider_relationship_type: str | None = None
    provider_item: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VendorLeadUpsertRequest(BaseModel):
    opportunity_id: int = Field(..., ge=1)
    lead_id: int | None = None
    status: str | None = None
    notes: str | None = None


class VendorQuoteOut(BaseModel):
    id: int
    opportunity_id: int
    cage: str
    company_name: str | None = None
    part_number: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: str
    unit_price: float | None = None
    lead_time_days: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SeedRequest(BaseModel):
    opportunity_id: int = Field(..., ge=1)


class UpsertRequest(BaseModel):
    opportunity_id: int = Field(..., ge=1)
    cage: str = Field(..., min_length=3, max_length=10)
    part_number: str | None = None

    company_name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None

    status: str | None = None
    unit_price: float | None = None
    lead_time_days: int | None = None
    notes: str | None = None
