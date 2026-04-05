from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from app.core.db import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id = Column(Integer, primary_key=True, index=True)
    legal_name = Column(String, nullable=False)
    uei = Column(String, nullable=True)
    cage = Column(String, nullable=True)
    naics_codes = Column(ARRAY(String), nullable=True)
    certifications = Column(ARRAY(String), nullable=True)
    capability_statement_url = Column(String, nullable=True)
    core_competencies = Column(Text, nullable=True)
    differentiators = Column(Text, nullable=True)
    past_performance_summary = Column(Text, nullable=True)
    annual_revenue = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
