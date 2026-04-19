from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils.enums import OpportunityStatus
from app.utils.title_normalizer import normalize_titles, build_summary_text


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)

    source: Mapped[str] = mapped_column(String(50), index=True)
    source_opportunity_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    solicitation_number: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(300))
    agency: Mapped[str] = mapped_column(String(200))
    sub_agency: Mapped[str | None] = mapped_column(String(200), nullable=True)
    office: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str] = mapped_column(String(500))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    naics: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fsc: Mapped[str | None] = mapped_column(String(10), nullable=True)
    set_aside: Mapped[str | None] = mapped_column(String(80), nullable=True)
    place_of_performance: Mapped[str | None] = mapped_column(String(200), nullable=True)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=OpportunityStatus.NEW.value, index=True)

    analysis = relationship(
        "OpportunityAnalysis",
        back_populates="opportunity",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs):
        alias_map = {
            "naics_code": "naics",
            "fsc_code": "fsc",
            "set_aside_type": "set_aside",
            "description": "raw_text",
        }
        for alias, real in alias_map.items():
            if alias in kwargs and real not in kwargs:
                kwargs[real] = kwargs.pop(alias)
        super().__init__(**kwargs)

    @property
    def naics_code(self):
        return self.naics

    @naics_code.setter
    def naics_code(self, value):
        self.naics = value

    @property
    def fsc_code(self):
        return self.fsc

    @fsc_code.setter
    def fsc_code(self, value):
        self.fsc = value

    @property
    def set_aside_type(self):
        return self.set_aside

    @set_aside_type.setter
    def set_aside_type(self, value):
        self.set_aside = value

    @property
    def description(self):
        return self.raw_text

    @description.setter
    def description(self, value):
        self.raw_text = value

    @property
    def workspace_url(self):
        return f"/workspace/{self.id}"

    @property
    def workspace_api_url(self):
        return f"/api/workspace/summary?opp_id={self.id}"

    @property
    def raw_title(self):
        return self.title

    @property
    def display_title(self):
        return normalize_titles(
            source=self.source,
            raw_title=self.title,
            solicitation_number=self.solicitation_number,
            source_opportunity_id=self.source_opportunity_id,
            raw_payload=self.raw_payload,
            parsed_json=self.parsed_json,
            raw_text=self.raw_text,
        )["display_title"]

    @property
    def source_uniform_title(self):
        return normalize_titles(
            source=self.source,
            raw_title=self.title,
            solicitation_number=self.solicitation_number,
            source_opportunity_id=self.source_opportunity_id,
            raw_payload=self.raw_payload,
            parsed_json=self.parsed_json,
            raw_text=self.raw_text,
        )["source_uniform_title"]

    @property
    def summary_text(self):
        return build_summary_text(self.raw_text, self.parsed_json, self.raw_payload)


class OpportunityAnalysis(Base):
    __tablename__ = "opportunity_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)

    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity = relationship("Opportunity", back_populates="analysis")
