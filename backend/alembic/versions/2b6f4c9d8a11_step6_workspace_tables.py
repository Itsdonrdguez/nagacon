"""step6 workspace artifacts, tasks, parsed_json

Revision ID: 2b6f4c9d8a11
Revises: 9c1f3b7a1d0c
Create Date: 2026-02-23 20:23:16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "2b6f4c9d8a11"
down_revision = "9c1f3b7a1d0c"
branch_labels = None
depends_on = None


def upgrade():
    # opportunities.parsed_json (jsonb)
    op.add_column("opportunities", sa.Column("parsed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # workspace_artifacts
    op.create_table(
        "workspace_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    # workspace_tasks
    op.create_table(
        "workspace_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("workspace_tasks")
    op.drop_table("workspace_artifacts")
    op.drop_column("opportunities", "parsed_json")
