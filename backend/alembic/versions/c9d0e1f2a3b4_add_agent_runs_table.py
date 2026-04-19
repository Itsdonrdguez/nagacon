"""add agent runs table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-04-06 20:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    enum_name = "agent_type"
    existing_tables = set(inspector.get_table_names())

    if bind.dialect.name == "postgresql":
        agent_type_enum = postgresql.ENUM(
            "opportunity_analyzer",
            "vendor_discovery",
            "pricing",
            "proposal",
            name=enum_name,
            create_type=False,
        )
        agent_type_enum.create(bind, checkfirst=True)
        agent_type_column = agent_type_enum
        json_type = postgresql.JSONB(astext_type=sa.Text())
    else:
        agent_type_column = sa.Enum(
            "opportunity_analyzer",
            "vendor_discovery",
            "pricing",
            "proposal",
            name=enum_name,
        )
        json_type = sa.JSON()

    if "agent_runs" not in existing_tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id"), nullable=True),
            sa.Column("agent_type", agent_type_column, nullable=False),
            sa.Column("input_payload", json_type, nullable=True),
            sa.Column("output_payload", json_type, nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
        op.create_index("ix_agent_runs_id", "agent_runs", ["id"], unique=False)
        op.create_index("ix_agent_runs_opportunity_id", "agent_runs", ["opportunity_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "agent_runs" in existing_tables:
        op.drop_index("ix_agent_runs_opportunity_id", table_name="agent_runs")
        op.drop_index("ix_agent_runs_id", table_name="agent_runs")
        op.drop_table("agent_runs")

    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="agent_type").drop(bind, checkfirst=True)
