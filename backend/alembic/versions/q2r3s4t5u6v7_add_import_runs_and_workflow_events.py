"""add import runs and workflow events

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-05-20 19:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "q2r3s4t5u6v7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("run_kind", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="started"),
        sa.Column("source_hash", sa.String(length=128), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("inserted_count", sa.Integer(), nullable=True),
        sa.Column("updated_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("duplicate_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_import_runs_id", "import_runs", ["id"])
    op.create_index("ix_import_runs_organization_id", "import_runs", ["organization_id"])
    op.create_index("ix_import_runs_user_id", "import_runs", ["user_id"])
    op.create_index("ix_import_runs_source", "import_runs", ["source"])
    op.create_index("ix_import_runs_run_kind", "import_runs", ["run_kind"])
    op.create_index("ix_import_runs_status", "import_runs", ["status"])
    op.create_index("ix_import_runs_source_hash", "import_runs", ["source_hash"])

    op.create_table(
        "opportunity_workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("from_state", sa.String(length=40), nullable=True),
        sa.Column("to_state", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_opportunity_workflow_events_id", "opportunity_workflow_events", ["id"])
    op.create_index("ix_opportunity_workflow_events_organization_id", "opportunity_workflow_events", ["organization_id"])
    op.create_index("ix_opportunity_workflow_events_opportunity_id", "opportunity_workflow_events", ["opportunity_id"])
    op.create_index("ix_opportunity_workflow_events_user_id", "opportunity_workflow_events", ["user_id"])
    op.create_index("ix_opportunity_workflow_events_entity_type", "opportunity_workflow_events", ["entity_type"])
    op.create_index("ix_opportunity_workflow_events_entity_id", "opportunity_workflow_events", ["entity_id"])
    op.create_index("ix_opportunity_workflow_events_action", "opportunity_workflow_events", ["action"])


def downgrade() -> None:
    op.drop_index("ix_opportunity_workflow_events_action", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_entity_id", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_entity_type", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_user_id", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_opportunity_id", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_organization_id", table_name="opportunity_workflow_events")
    op.drop_index("ix_opportunity_workflow_events_id", table_name="opportunity_workflow_events")
    op.drop_table("opportunity_workflow_events")

    op.drop_index("ix_import_runs_source_hash", table_name="import_runs")
    op.drop_index("ix_import_runs_status", table_name="import_runs")
    op.drop_index("ix_import_runs_run_kind", table_name="import_runs")
    op.drop_index("ix_import_runs_source", table_name="import_runs")
    op.drop_index("ix_import_runs_user_id", table_name="import_runs")
    op.drop_index("ix_import_runs_organization_id", table_name="import_runs")
    op.drop_index("ix_import_runs_id", table_name="import_runs")
    op.drop_table("import_runs")
