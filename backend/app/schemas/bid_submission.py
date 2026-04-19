from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class BidSubmissionOut(BaseModel):
    id: int
    opportunity_id: int
    status: str
    submitted_at: datetime | None = None
    submitted_unit_price: float | None = None
    submitted_vendor_cage: str | None = None
    submitted_vendor_name: str | None = None
    planned_vendor_quote_id: int | None = None
    planned_vendor_cage: str | None = None
    planned_vendor_name: str | None = None
    awarded_at: datetime | None = None
    award_amount: float | None = None
    winning_vendor_cage: str | None = None
    winning_vendor_name: str | None = None
    outcome_summary: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BidSubmissionUpsert(BaseModel):
    opportunity_id: int = Field(..., ge=1)
    status: str | None = None
    submitted_at: datetime | None = None
    submitted_unit_price: float | None = None
    submitted_vendor_cage: str | None = None
    submitted_vendor_name: str | None = None
    planned_vendor_quote_id: int | None = None
    planned_vendor_cage: str | None = None
    planned_vendor_name: str | None = None
    awarded_at: datetime | None = None
    award_amount: float | None = None
    winning_vendor_cage: str | None = None
    winning_vendor_name: str | None = None
    outcome_summary: str | None = None
    notes: str | None = None
