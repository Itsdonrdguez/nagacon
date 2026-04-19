"""add provider identity fields

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-04-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("canonical_name", sa.String(length=300), nullable=True))
    op.add_column("providers", sa.Column("identity_source", sa.String(length=100), nullable=True))
    op.add_column("providers", sa.Column("identity_confidence", sa.Float(), nullable=True))
    op.add_column("providers", sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(op.f("ix_providers_canonical_name"), "providers", ["canonical_name"], unique=False)
    op.create_index(op.f("ix_providers_identity_source"), "providers", ["identity_source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_providers_identity_source"), table_name="providers")
    op.drop_index(op.f("ix_providers_canonical_name"), table_name="providers")
    op.drop_column("providers", "aliases")
    op.drop_column("providers", "identity_confidence")
    op.drop_column("providers", "identity_source")
    op.drop_column("providers", "canonical_name")
