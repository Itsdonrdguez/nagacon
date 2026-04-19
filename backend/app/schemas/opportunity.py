from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, computed_field

from app.utils.enums import OpportunityStatus
from app.utils.solicitation_status import derive_solicitation_status
from app.utils.title_normalizer import normalize_source_title


class RawOpportunity(BaseModel):
    source: str
    source_opportunity_id: str | None = None
    solicitation_number: str | None = None
    title: str | None = None
    agency: str | None = None
    sub_agency: str | None = None
    office: str | None = None
    url: str | None = None
    posted_at: str | datetime | None = None
    due_at: str | datetime | None = None
    set_aside_type: str | None = None
    naics_code: str | None = None
    fsc_code: str | None = None
    place_of_performance: str | None = None
    description: str | None = None
    raw_payload: dict[str, Any] | None = None


class OpportunityBase(BaseModel):
    source: str
    source_opportunity_id: str | None = None
    solicitation_number: str | None = None
    title: str
    agency: str | None = None
    sub_agency: str | None = None
    office: str | None = None
    url: str | None = None
    posted_at: datetime | None = None
    due_at: datetime | None = None
    set_aside_type: str | None = None
    naics_code: str | None = None
    fsc_code: str | None = None
    place_of_performance: str | None = None
    description: str | None = None
    status: OpportunityStatus = OpportunityStatus.NEW
    raw_payload: dict[str, Any] | None = None


class OpportunityCreate(OpportunityBase):
    pass


class OpportunityUpdate(BaseModel):
    source_opportunity_id: str | None = None
    solicitation_number: str | None = None
    title: str | None = None
    agency: str | None = None
    sub_agency: str | None = None
    office: str | None = None
    url: str | None = None
    posted_at: datetime | None = None
    due_at: datetime | None = None
    set_aside_type: str | None = None
    naics_code: str | None = None
    fsc_code: str | None = None
    place_of_performance: str | None = None
    description: str | None = None
    status: OpportunityStatus | None = None
    raw_payload: dict[str, Any] | None = None


class OpportunityRead(OpportunityBase):
    id: int
    decision_status: str | None = None

    @computed_field
    @property
    def workspace_url(self) -> str:
        return f"/workspace/{self.id}"

    @computed_field
    @property
    def display_title(self) -> str:
        return normalize_source_title(
            source=self.source,
            title=self.title,
            solicitation_number=self.solicitation_number,
            source_opportunity_id=self.source_opportunity_id,
            description=self.description,
            raw_payload=self.raw_payload,
        )

    @computed_field
    @property
    def source_uniform_title(self) -> str:
        return self.display_title

    @computed_field
    @property
    def solicitation_status(self) -> str:
        return derive_solicitation_status(self.due_at)

    @computed_field
    @property
    def bid_eligible(self) -> bool:
        return self.solicitation_status != "CLOSED"

    @computed_field
    @property
    def intelligence_eligible(self) -> bool:
        return True

    @computed_field
    @property
    def workflow_label(self) -> str:
        if self.solicitation_status == "CLOSED":
            return "Closed / Intelligence"
        if self.solicitation_status == "DUE_SOON":
            return "Closing Soon"
        return "Active"

    @computed_field
    @property
    def primary_action_label(self) -> str:
        return "Analyze Intelligence" if self.solicitation_status == "CLOSED" else "Work Opportunity"

    @computed_field
    @property
    def days_since_close(self) -> int | None:
        if not self.due_at or self.solicitation_status != "CLOSED":
            return None
        return max((datetime.utcnow() - self.due_at).days, 0)

    @computed_field
    @property
    def award_expected_after(self) -> datetime | None:
        if not self.due_at:
            return None
        return self.due_at + timedelta(days=90)

    @computed_field
    @property
    def award_intelligence_status(self) -> str:
        if self.solicitation_status != "CLOSED":
            return "ACTIVE_RFQ"
        days = self.days_since_close or 0
        if days < 90:
            return "AWAITING_USASPENDING"
        return "READY_FOR_USASPENDING_CHECK"

    @computed_field
    @property
    def award_follow_up_eligible(self) -> bool:
        return self.award_intelligence_status == "READY_FOR_USASPENDING_CHECK"

    model_config = {"from_attributes": True}


class IngestResult(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
