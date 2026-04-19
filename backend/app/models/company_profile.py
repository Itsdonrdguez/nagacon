from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from app.core.db import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    legal_name = Column(String, nullable=False)
    uei = Column(String, nullable=True)
    cage = Column(String, nullable=True)
    website = Column(String, nullable=True)
    primary_contact_name = Column(String, nullable=True)
    primary_contact_email = Column(String, nullable=True)
    primary_contact_phone = Column(String, nullable=True)
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True)
    naics_codes = Column(ARRAY(String), nullable=True)
    certifications = Column(ARRAY(String), nullable=True)
    capability_statement_url = Column(String, nullable=True)
    core_competencies = Column(Text, nullable=True)
    differentiators = Column(Text, nullable=True)
    past_performance_summary = Column(Text, nullable=True)
    annual_revenue = Column(Float, nullable=True)
    preferred_dibbs_fsc_codes = Column(ARRAY(String), nullable=True)
    preferred_sam_naics_codes = Column(ARRAY(String), nullable=True)
    preferred_sam_keywords = Column(ARRAY(String), nullable=True)
    preferred_sam_agencies = Column(ARRAY(String), nullable=True)
    preferred_sam_states = Column(ARRAY(String), nullable=True)
    auto_ingest_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_ingest_limit = Column(Integer, nullable=True)
    auto_ingest_interval_hours = Column(Integer, nullable=True)
    last_auto_ingest_at = Column(DateTime, nullable=True)
    dibbs_pdf_download_limit = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
