
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.db import Base


class VendorOpportunityMatch(Base):
    __tablename__ = "vendor_opportunity_matches"
    __table_args__ = (
        UniqueConstraint("vendor_id", "opportunity_id", name="uq_vendor_match_vendor_opp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendor_leads.id"), nullable=False, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=False, index=True)
    match_reason = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    source = Column(String, nullable=True, default="rule_based")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
