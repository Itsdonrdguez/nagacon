"""add dibbs pdf download limit

Revision ID: f7a8b9c0d1e2
Revises: f4c5d6e7f8g9
Create Date: 2026-04-14 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "f4c5d6e7f8g9"
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

    if not _column_exists(inspector, "company_profiles", "dibbs_pdf_download_limit"):
        op.add_column("company_profiles", sa.Column("dibbs_pdf_download_limit", sa.Integer(), nullable=True))

    company_profiles = sa.table(
        "company_profiles",
        sa.column("dibbs_pdf_download_limit", sa.Integer()),
    )
    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.dibbs_pdf_download_limit.is_(None))
        .values(dibbs_pdf_download_limit=25)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    if _column_exists(inspector, "company_profiles", "dibbs_pdf_download_limit"):
        op.drop_column("company_profiles", "dibbs_pdf_download_limit")
