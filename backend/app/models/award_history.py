from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AwardHistory(Base):
    __tablename__ = "award_history"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "dedupe_key", name="uq_award_history_opp_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)

    source_system: Mapped[str] = mapped_column(String(80), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(360), index=True)
    nsn: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    fsc: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)

    award_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    piid: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    modification_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    solicitation_id: Mapped[str | None] = mapped_column(String(160), nullable=True)

    recipient_name: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    recipient_cage: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    recipient_uei: Mapped[str | None] = mapped_column(String(80), nullable=True)

    awarding_agency: Mapped[str | None] = mapped_column(String(240), index=True, nullable=True)
    contracting_department: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contracting_subtier: Mapped[str | None] = mapped_column(String(240), nullable=True)
    award_date: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    award_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    psc_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    naics_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_confidence: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    match_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
