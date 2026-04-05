from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class QuoteBase(BaseModel):
    opportunity_id: int
    vendor_id: Optional[int] = None
    line_item: str
    quantity: float = Field(ge=0)
    unit_cost: float = Field(ge=0)
    markup_pct: float = Field(default=0.0, ge=0)
    assumptions: Optional[str] = None


class QuoteCreate(QuoteBase):
    pass


class QuoteUpdate(BaseModel):
    line_item: Optional[str] = None
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    markup_pct: Optional[float] = Field(default=None, ge=0)
    assumptions: Optional[str] = None
    vendor_id: Optional[int] = None


class QuoteOut(QuoteBase):
    id: int
    sell_price: Optional[float] = None
    total_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
