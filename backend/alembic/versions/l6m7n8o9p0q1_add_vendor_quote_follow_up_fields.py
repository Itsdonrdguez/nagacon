"""add vendor quote follow up fields

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-04-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "l6m7n8o9p0q1"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendor_quotes", sa.Column("requested_at", sa.DateTime(), nullable=True))
    op.add_column("vendor_quotes", sa.Column("last_follow_up_at", sa.DateTime(), nullable=True))
    op.add_column("vendor_quotes", sa.Column("next_follow_up_at", sa.DateTime(), nullable=True))
    op.add_column("vendor_quotes", sa.Column("follow_up_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_vendor_quotes_requested_at"), "vendor_quotes", ["requested_at"], unique=False)
    op.create_index(op.f("ix_vendor_quotes_next_follow_up_at"), "vendor_quotes", ["next_follow_up_at"], unique=False)
    op.alter_column("vendor_quotes", "follow_up_count", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_vendor_quotes_next_follow_up_at"), table_name="vendor_quotes")
    op.drop_index(op.f("ix_vendor_quotes_requested_at"), table_name="vendor_quotes")
    op.drop_column("vendor_quotes", "follow_up_count")
    op.drop_column("vendor_quotes", "next_follow_up_at")
    op.drop_column("vendor_quotes", "last_follow_up_at")
    op.drop_column("vendor_quotes", "requested_at")
