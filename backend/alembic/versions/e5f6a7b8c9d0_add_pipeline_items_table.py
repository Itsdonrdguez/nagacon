"""add pipeline items table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9, 7f7a57fa58ea
Create Date: 2026-04-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = ("d4e5f6a7b8c9", "7f7a57fa58ea")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in inspector.get_indexes(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    pipeline_status = sa.Enum(
        "NEW",
        "IN_PROGRESS",
        "BID",
        "NO_BID",
        "SUBMITTED",
        name="pipeline_status",
    )
    pipeline_status.create(bind, checkfirst=True)

    pipeline_status_column = postgresql.ENUM(
        "NEW",
        "IN_PROGRESS",
        "BID",
        "NO_BID",
        "SUBMITTED",
        name="pipeline_status",
        create_type=False,
    )

    if not _table_exists(inspector, "pipeline_items"):
        op.create_table(
            "pipeline_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id"), nullable=False),
            sa.Column("decision_status", pipeline_status_column, nullable=False, server_default="NEW"),
            sa.Column("owner", sa.String(), nullable=True),
            sa.Column("priority", sa.String(), nullable=True),
            sa.Column("probability_of_win", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("target_submit_date", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("opportunity_id", name="uq_pipeline_items_opportunity_id"),
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "pipeline_items", "ix_pipeline_items_id"):
        op.create_index("ix_pipeline_items_id", "pipeline_items", ["id"])
    if not _index_exists(inspector, "pipeline_items", "ix_pipeline_items_opportunity_id"):
        op.create_index("ix_pipeline_items_opportunity_id", "pipeline_items", ["opportunity_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "pipeline_items"):
        if _index_exists(inspector, "pipeline_items", "ix_pipeline_items_opportunity_id"):
            op.drop_index("ix_pipeline_items_opportunity_id", table_name="pipeline_items")
        if _index_exists(inspector, "pipeline_items", "ix_pipeline_items_id"):
            op.drop_index("ix_pipeline_items_id", table_name="pipeline_items")
        op.drop_table("pipeline_items")

    pipeline_status = sa.Enum(
        "NEW",
        "IN_PROGRESS",
        "BID",
        "NO_BID",
        "SUBMITTED",
        name="pipeline_status",
    )
    pipeline_status.drop(bind, checkfirst=True)
