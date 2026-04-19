from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BidSubmission(Base):
    __tablename__ = "bid_submissions"
    __table_args__ = (
        UniqueConstraint("opportunity_id", name="uq_bid_submissions_opportunity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # DRAFT / SUBMITTED / AWARDED / LOST / NO_BID
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    submitted_unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    submitted_vendor_cage: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    submitted_vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_vendor_quote_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    planned_vendor_cage: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    planned_vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    award_amount: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    winning_vendor_cage: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    winning_vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity = relationship("Opportunity", backref="bid_submission", uselist=False)
