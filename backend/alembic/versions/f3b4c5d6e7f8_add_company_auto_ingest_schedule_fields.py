"""add company auto ingest schedule fields

Revision ID: f3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    try:
        return column_name in {column["name"] for column in inspector.get_columns(table_name)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    if not _column_exists(inspector, "company_profiles", "auto_ingest_interval_hours"):
        op.add_column("company_profiles", sa.Column("auto_ingest_interval_hours", sa.Integer(), nullable=True))
    if not _column_exists(inspector, "company_profiles", "last_auto_ingest_at"):
        op.add_column("company_profiles", sa.Column("last_auto_ingest_at", sa.DateTime(), nullable=True))

    company_profiles = sa.table(
        "company_profiles",
        sa.column("auto_ingest_interval_hours", sa.Integer()),
    )
    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.auto_ingest_interval_hours.is_(None))
        .values(auto_ingest_interval_hours=24)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    if _column_exists(inspector, "company_profiles", "last_auto_ingest_at"):
        op.drop_column("company_profiles", "last_auto_ingest_at")
    if _column_exists(inspector, "company_profiles", "auto_ingest_interval_hours"):
        op.drop_column("company_profiles", "auto_ingest_interval_hours")
