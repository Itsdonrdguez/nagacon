"""add auth fields to users

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("session_token_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("session_expires_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_users_session_token_hash"), "users", ["session_token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_session_token_hash"), table_name="users")
    op.drop_column("users", "session_expires_at")
    op.drop_column("users", "session_token_hash")
    op.drop_column("users", "password_hash")
