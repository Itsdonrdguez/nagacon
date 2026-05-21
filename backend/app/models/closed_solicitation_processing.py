from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ClosedSolicitationProcessingRecord(Base):
    __tablename__ = "closed_solicitation_processing_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "opportunity_id",
            "file_sha256",
            name="uq_closed_solicitation_processing_org_opp_hash",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True, nullable=True)
    opportunity_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunity_files.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    solicitation_number: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    nsn: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    part_numbers: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    vendor_names: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    cage_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    pricing_history_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_source_file_name: Mapped[str | None] = mapped_column(String(260), nullable=True)
    original_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path_before_deletion: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    extraction_status: Mapped[str] = mapped_column(String(40), index=True, default="queued")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deletion_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
