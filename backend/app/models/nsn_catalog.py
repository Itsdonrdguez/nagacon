from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class NsnCatalogImportRun(Base):
    __tablename__ = "nsn_catalog_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_name: Mapped[str] = mapped_column(String(80), index=True)
    source_version: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(700), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", server_default="pending", index=True)
    rows_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rows_imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class NsnMaster(Base):
    __tablename__ = "nsn_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), unique=True, index=True)
    fsc: Mapped[str] = mapped_column(String(4), index=True)
    niin: Mapped[str] = mapped_column(String(9), index=True)
    item_name: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    item_name_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    demil_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    criticality_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    public_data_status: Mapped[str] = mapped_column(String(40), default="public", server_default="public", index=True)
    source_name: Mapped[str] = mapped_column(String(80), default="manual", server_default="manual", index=True)
    source_version: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class NsnReference(Base):
    __tablename__ = "nsn_references"
    __table_args__ = (
        UniqueConstraint("compact_nsn", "cage", "part_number", "source_name", name="uq_nsn_reference_nsn_cage_part_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    fsc: Mapped[str | None] = mapped_column(String(4), index=True, nullable=True)
    niin: Mapped[str | None] = mapped_column(String(9), index=True, nullable=True)
    cage: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    relationship_type: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    source_name: Mapped[str] = mapped_column(String(80), index=True)
    source_version: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class NsnInterchangeability(Base):
    __tablename__ = "nsn_interchangeability"
    __table_args__ = (
        UniqueConstraint("compact_nsn", "related_compact_nsn", "relationship_type", "source_name", name="uq_nsn_interchangeability_pair_type_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    related_nsn: Mapped[str] = mapped_column(String(40), index=True)
    related_compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    relationship_type: Mapped[str] = mapped_column(String(80), index=True)
    order_of_use: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_name: Mapped[str] = mapped_column(String(80), index=True)
    source_version: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class NsnEvidence(Base):
    __tablename__ = "nsn_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    claim_type: Mapped[str] = mapped_column(String(80), index=True)
    claim_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_name: Mapped[str] = mapped_column(String(80), index=True)
    source_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    matched_by: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class NsnIntelligenceSnapshot(Base):
    __tablename__ = "nsn_intelligence_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    source_scope: Mapped[str] = mapped_column(String(80), default="catalog", server_default="catalog", index=True)
    summary_json: Mapped[dict] = mapped_column(JSONB)
    confidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class NsnAwardEvidence(Base):
    __tablename__ = "nsn_award_evidence"
    __table_args__ = (
        UniqueConstraint("compact_nsn", "source_system", "dedupe_key", name="uq_nsn_award_evidence_nsn_source_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nsn: Mapped[str] = mapped_column(String(40), index=True)
    compact_nsn: Mapped[str] = mapped_column(String(13), index=True)
    fsc: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)

    source_system: Mapped[str] = mapped_column(String(80), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(360), index=True)
    award_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    piid: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    recipient_cage: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    recipient_uei: Mapped[str | None] = mapped_column(String(80), nullable=True)
    awarding_agency: Mapped[str | None] = mapped_column(String(240), index=True, nullable=True)
    award_date: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    award_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    psc_code: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)

    matched_by: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_confidence: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    match_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
