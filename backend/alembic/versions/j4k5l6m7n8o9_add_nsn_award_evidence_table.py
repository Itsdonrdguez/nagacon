"""add nsn award evidence table

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nsn_award_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nsn", sa.String(length=40), nullable=False),
        sa.Column("compact_nsn", sa.String(length=13), nullable=False),
        sa.Column("fsc", sa.String(length=10), nullable=True),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("dedupe_key", sa.String(length=360), nullable=False),
        sa.Column("award_id", sa.String(length=160), nullable=True),
        sa.Column("piid", sa.String(length=160), nullable=True),
        sa.Column("recipient_name", sa.String(length=300), nullable=True),
        sa.Column("recipient_cage", sa.String(length=20), nullable=True),
        sa.Column("recipient_uei", sa.String(length=80), nullable=True),
        sa.Column("awarding_agency", sa.String(length=240), nullable=True),
        sa.Column("award_date", sa.String(length=40), nullable=True),
        sa.Column("award_amount", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("psc_code", sa.String(length=20), nullable=True),
        sa.Column("matched_by", sa.String(length=120), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_confidence", sa.String(length=40), nullable=True),
        sa.Column("match_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("compact_nsn", "source_system", "dedupe_key", name="uq_nsn_award_evidence_nsn_source_key"),
    )
    for column in [
        "id",
        "nsn",
        "compact_nsn",
        "fsc",
        "source_system",
        "dedupe_key",
        "award_id",
        "piid",
        "recipient_name",
        "recipient_cage",
        "awarding_agency",
        "award_date",
        "psc_code",
        "matched_by",
        "match_confidence",
    ]:
        op.create_index(op.f(f"ix_nsn_award_evidence_{column}"), "nsn_award_evidence", [column], unique=False)


def downgrade() -> None:
    for column in [
        "match_confidence",
        "matched_by",
        "psc_code",
        "award_date",
        "awarding_agency",
        "recipient_cage",
        "recipient_name",
        "piid",
        "award_id",
        "dedupe_key",
        "source_system",
        "fsc",
        "compact_nsn",
        "nsn",
        "id",
    ]:
        op.drop_index(op.f(f"ix_nsn_award_evidence_{column}"), table_name="nsn_award_evidence")
    op.drop_table("nsn_award_evidence")
