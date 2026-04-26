from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.db import Base


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id = Column(String(80), primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    kind = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="queued", index=True)
    payload = Column(JSONB, nullable=True)
    progress = Column(JSONB, nullable=True)
    result = Column(JSONB, nullable=True)
    events = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
