from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BidSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

class BidSubmissionUpsert(BaseModel):
    opportunity_id: int = Field(..., ge=1)
    status: str | None = None
    approved: bool | None = None
    approval_notes: str | None = None
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
