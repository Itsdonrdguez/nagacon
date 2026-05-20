from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, computed_field

from app.utils.enums import OpportunityStatus
from app.utils.opportunity_lifecycle import ARCHIVE_CUTOFF_DAYS, derive_opportunity_lifecycle
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
    parsed_json: dict[str, Any] | None = None
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
    has_workspace: bool = False
    decision_status: str | None = None
    pipeline_owner: str | None = None
    target_submit_date: datetime | None = None

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
    def opportunity_lifecycle(self) -> str:
        return derive_opportunity_lifecycle(self.due_at)

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
        if self.opportunity_lifecycle == "ARCHIVED":
            return "Archive"
        if self.solicitation_status == "CLOSED":
            return "Closed / Intelligence"
        if self.solicitation_status == "DUE_SOON":
            return "Closing Soon"
        return "Active"

    @computed_field
    @property
    def primary_action_label(self) -> str:
        if self.opportunity_lifecycle == "ARCHIVED":
            return "Open Archive"
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
        if self.opportunity_lifecycle == "ARCHIVED":
            return "ARCHIVED"
        days = self.days_since_close or 0
        if days < 90:
            return "AWAITING_USASPENDING"
        return "READY_FOR_USASPENDING_CHECK"

    @computed_field
    @property
    def award_follow_up_eligible(self) -> bool:
        return self.award_intelligence_status == "READY_FOR_USASPENDING_CHECK"

    @computed_field
    @property
    def archive_cutoff_days(self) -> int:
        return ARCHIVE_CUTOFF_DAYS

    @computed_field
    @property
    def archive_after(self) -> datetime | None:
        if not self.due_at:
            return None
        return self.due_at + timedelta(days=ARCHIVE_CUTOFF_DAYS)

    @computed_field
    @property
    def requested_quantity(self) -> str | None:
        payload = self.raw_payload if isinstance(self.raw_payload, dict) else {}
        search_row = payload.get("dibbs_search_row") if isinstance(payload.get("dibbs_search_row"), dict) else {}
        qty = _clean_quantity(search_row.get("quantity"))
        if qty:
            return qty

        dibbs_detail = payload.get("dibbs_detail") if isinstance(payload.get("dibbs_detail"), dict) else {}
        structured = dibbs_detail.get("structured") if isinstance(dibbs_detail.get("structured"), dict) else dibbs_detail
        solicitations = structured.get("solicitations") if isinstance(structured, dict) else []
        if isinstance(solicitations, list):
            for row in solicitations:
                if not isinstance(row, dict):
                    continue
                if self.solicitation_number and row.get("solicitation_number"):
                    left = "".join(ch for ch in str(self.solicitation_number) if ch.isalnum()).upper()
                    right = "".join(ch for ch in str(row.get("solicitation_number")) if ch.isalnum()).upper()
                    if left and right and left != right:
                        continue
                qty = _clean_quantity(row.get("qty") or row.get("quantity"))
                if qty:
                    return qty

        return None

    @computed_field
    @property
    def requested_quantity_display(self) -> str | None:
        return f"Qty: {self.requested_quantity}" if self.requested_quantity else None

    @computed_field
    @property
    def prepared_summary(self) -> str | None:
        parsed = self.parsed_json if isinstance(self.parsed_json, dict) else {}
        sam_intelligence = parsed.get("sam_intelligence") if isinstance(parsed.get("sam_intelligence"), dict) else None
        if sam_intelligence and sam_intelligence.get("summary"):
            return str(sam_intelligence.get("summary"))
        return None

    @computed_field
    @property
    def prepared_requirements(self) -> list[str]:
        parsed = self.parsed_json if isinstance(self.parsed_json, dict) else {}
        sam_intelligence = parsed.get("sam_intelligence") if isinstance(parsed.get("sam_intelligence"), dict) else None
        if sam_intelligence and isinstance(sam_intelligence.get("requirements"), list):
            return [str(item) for item in sam_intelligence.get("requirements") if str(item).strip()]
        return []

    @computed_field
    @property
    def prepared_risk_flags(self) -> list[str]:
        parsed = self.parsed_json if isinstance(self.parsed_json, dict) else {}
        sam_intelligence = parsed.get("sam_intelligence") if isinstance(parsed.get("sam_intelligence"), dict) else None
        if sam_intelligence and isinstance(sam_intelligence.get("risk_flags"), list):
            return [str(item) for item in sam_intelligence.get("risk_flags") if str(item).strip()]
        return []

    model_config = {"from_attributes": True}


class IngestResult(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


def _clean_quantity(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.replace(",", "")
