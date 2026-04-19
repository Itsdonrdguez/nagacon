from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "source_file_id",
            "award_id",
            "cage",
            "unit_price",
            name="uq_price_history_opp_file_award_cage_price",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("opportunity_files.id", ondelete="SET NULL"), index=True, nullable=True)

    nsn: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    award_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    award_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(240), index=True, nullable=True)
    cage: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
