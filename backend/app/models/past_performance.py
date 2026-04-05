from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from app.core.db import Base


class PastPerformance(Base):
    __tablename__ = "past_performances"

    id = Column(Integer, primary_key=True, index=True)
    company_profile_id = Column(Integer, ForeignKey("company_profiles.id"), nullable=True, index=True)
    client_name = Column(String, nullable=False)
    project_title = Column(String, nullable=False)
    project_value = Column(Float, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    naics_code = Column(String, nullable=True)
    relevance_tags = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
