"""add award history table

Revision ID: g1h2i3j4k5l6
Revises: f9c0d1e2f3g4
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "g1h2i3j4k5l6"
down_revision = "f9c0d1e2f3g4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "award_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("dedupe_key", sa.String(length=360), nullable=False),
        sa.Column("nsn", sa.String(length=40), nullable=True),
        sa.Column("fsc", sa.String(length=10), nullable=True),
        sa.Column("award_id", sa.String(length=160), nullable=True),
        sa.Column("piid", sa.String(length=160), nullable=True),
        sa.Column("modification_number", sa.String(length=80), nullable=True),
        sa.Column("solicitation_id", sa.String(length=160), nullable=True),
        sa.Column("recipient_name", sa.String(length=300), nullable=True),
        sa.Column("recipient_cage", sa.String(length=20), nullable=True),
        sa.Column("recipient_uei", sa.String(length=80), nullable=True),
        sa.Column("awarding_agency", sa.String(length=240), nullable=True),
        sa.Column("contracting_department", sa.String(length=240), nullable=True),
        sa.Column("contracting_subtier", sa.String(length=240), nullable=True),
        sa.Column("award_date", sa.String(length=40), nullable=True),
        sa.Column("award_amount", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("psc_code", sa.String(length=20), nullable=True),
        sa.Column("naics_code", sa.String(length=20), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_confidence", sa.String(length=40), nullable=True),
        sa.Column("match_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_id", "dedupe_key", name="uq_award_history_opp_dedupe_key"),
    )
    op.create_index(op.f("ix_award_history_id"), "award_history", ["id"], unique=False)
    op.create_index(op.f("ix_award_history_organization_id"), "award_history", ["organization_id"], unique=False)
    op.create_index(op.f("ix_award_history_opportunity_id"), "award_history", ["opportunity_id"], unique=False)
    op.create_index(op.f("ix_award_history_source_system"), "award_history", ["source_system"], unique=False)
    op.create_index(op.f("ix_award_history_dedupe_key"), "award_history", ["dedupe_key"], unique=False)
    op.create_index(op.f("ix_award_history_nsn"), "award_history", ["nsn"], unique=False)
    op.create_index(op.f("ix_award_history_fsc"), "award_history", ["fsc"], unique=False)
    op.create_index(op.f("ix_award_history_award_id"), "award_history", ["award_id"], unique=False)
    op.create_index(op.f("ix_award_history_piid"), "award_history", ["piid"], unique=False)
    op.create_index(op.f("ix_award_history_recipient_name"), "award_history", ["recipient_name"], unique=False)
    op.create_index(op.f("ix_award_history_recipient_cage"), "award_history", ["recipient_cage"], unique=False)
    op.create_index(op.f("ix_award_history_awarding_agency"), "award_history", ["awarding_agency"], unique=False)
    op.create_index(op.f("ix_award_history_award_date"), "award_history", ["award_date"], unique=False)
    op.create_index(op.f("ix_award_history_psc_code"), "award_history", ["psc_code"], unique=False)
    op.create_index(op.f("ix_award_history_naics_code"), "award_history", ["naics_code"], unique=False)
    op.create_index(op.f("ix_award_history_match_confidence"), "award_history", ["match_confidence"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_award_history_match_confidence"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_naics_code"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_psc_code"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_award_date"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_awarding_agency"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_recipient_cage"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_recipient_name"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_piid"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_award_id"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_fsc"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_nsn"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_dedupe_key"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_source_system"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_opportunity_id"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_organization_id"), table_name="award_history")
    op.drop_index(op.f("ix_award_history_id"), table_name="award_history")
    op.drop_table("award_history")
