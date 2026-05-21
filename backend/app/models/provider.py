from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)

    company_name: Mapped[str] = mapped_column(String(240), index=True)
    cage: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    uei: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(240), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", server_default="active", index=True)
    canonical_name: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    identity_source: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    identity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    aliases: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    items = relationship("ProviderItem", back_populates="provider", cascade="all, delete-orphan")


class ProviderItem(Base):
    __tablename__ = "provider_items"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "nsn",
            "relationship_type",
            "source",
            name="uq_provider_item_provider_nsn_type_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)

    nsn: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    fsc: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    nomenclature: Mapped[str | None] = mapped_column(String(300), index=True, nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(60), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    source_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    provider = relationship("Provider", back_populates="items")
