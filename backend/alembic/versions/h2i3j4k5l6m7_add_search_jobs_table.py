"""add search jobs table

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_jobs",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_search_jobs_id"), "search_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_search_jobs_organization_id"), "search_jobs", ["organization_id"], unique=False)
    op.create_index(op.f("ix_search_jobs_kind"), "search_jobs", ["kind"], unique=False)
    op.create_index(op.f("ix_search_jobs_status"), "search_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_search_jobs_status"), table_name="search_jobs")
    op.drop_index(op.f("ix_search_jobs_kind"), table_name="search_jobs")
    op.drop_index(op.f("ix_search_jobs_organization_id"), table_name="search_jobs")
    op.drop_index(op.f("ix_search_jobs_id"), table_name="search_jobs")
    op.drop_table("search_jobs")
