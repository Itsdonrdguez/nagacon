from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VendorLead(Base):
    """Parsed supplier clues tied to an opportunity.

    Leads can exist even when we do not yet have enough structured data to create
    a quote-tracking record. This lets the parser surface companies and part
    numbers early, then promote only strong identifiers into vendor_quotes.
    """

    __tablename__ = "vendor_leads"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "cage", "company_name", "part_number", name="uq_vendor_leads_opp_cage_company_part"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
        nullable=True,
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        index=True,
    )

    source_type: Mapped[str] = mapped_column(String(40), default="APPROVED_SOURCE", index=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cage: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    part_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nsn: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=50)
    is_approved_source: Mapped[bool] = mapped_column(Boolean, default=True)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity = relationship("Opportunity", backref="vendor_leads")


class VendorQuote(Base):
    """Per-opportunity vendor quote tracking (manual enrichment)."""

    __tablename__ = "vendor_quotes"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "cage", "part_number", name="uq_vendor_quotes_opp_cage_part"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
        nullable=True,
    )

    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        index=True,
    )

    cage: Mapped[str] = mapped_column(String(10), index=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(80), nullable=True)

    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(String(24), default="NOT_REQUESTED", index=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity = relationship("Opportunity", backref="vendor_quotes")
