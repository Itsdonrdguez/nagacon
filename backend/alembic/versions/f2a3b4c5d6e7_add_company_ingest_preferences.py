"""add company ingest preferences

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-07 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


DEFAULT_DIBBS_FSC_CODES = [
    "6520",
    "8470",
    "6550",
    "5805",
    "5130",
    "5810",
    "5998",
    "5999",
    "1095",
    "6110",
    "6515",
]

DEFAULT_SAM_NAICS_CODES = [
    "561720",
    "561210",
    "561730",
    "561740",
    "561790",
    "484110",
    "484121",
    "484122",
    "488510",
    "492110",
    "492210",
    "485999",
    "488999",
]

DEFAULT_SAM_KEYWORDS = [
    "janitorial",
    "custodial",
    "cleaning",
    "facilities support",
    "transportation",
    "freight",
    "trucking",
    "logistics",
    "courier",
    "delivery",
]


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

    array_type = postgresql.ARRAY(sa.String())

    if not _column_exists(inspector, "company_profiles", "preferred_dibbs_fsc_codes"):
        op.add_column("company_profiles", sa.Column("preferred_dibbs_fsc_codes", array_type, nullable=True))
    if not _column_exists(inspector, "company_profiles", "preferred_sam_naics_codes"):
        op.add_column("company_profiles", sa.Column("preferred_sam_naics_codes", array_type, nullable=True))
    if not _column_exists(inspector, "company_profiles", "preferred_sam_keywords"):
        op.add_column("company_profiles", sa.Column("preferred_sam_keywords", array_type, nullable=True))
    if not _column_exists(inspector, "company_profiles", "preferred_sam_agencies"):
        op.add_column("company_profiles", sa.Column("preferred_sam_agencies", array_type, nullable=True))
    if not _column_exists(inspector, "company_profiles", "preferred_sam_states"):
        op.add_column("company_profiles", sa.Column("preferred_sam_states", array_type, nullable=True))
    if not _column_exists(inspector, "company_profiles", "auto_ingest_enabled"):
        op.add_column("company_profiles", sa.Column("auto_ingest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not _column_exists(inspector, "company_profiles", "auto_ingest_limit"):
        op.add_column("company_profiles", sa.Column("auto_ingest_limit", sa.Integer(), nullable=True))

    company_profiles = sa.table(
        "company_profiles",
        sa.column("preferred_dibbs_fsc_codes", array_type),
        sa.column("preferred_sam_naics_codes", array_type),
        sa.column("preferred_sam_keywords", array_type),
        sa.column("auto_ingest_enabled", sa.Boolean()),
        sa.column("auto_ingest_limit", sa.Integer()),
    )

    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.preferred_dibbs_fsc_codes.is_(None))
        .values(preferred_dibbs_fsc_codes=DEFAULT_DIBBS_FSC_CODES)
    )
    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.preferred_sam_naics_codes.is_(None))
        .values(preferred_sam_naics_codes=DEFAULT_SAM_NAICS_CODES)
    )
    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.preferred_sam_keywords.is_(None))
        .values(preferred_sam_keywords=DEFAULT_SAM_KEYWORDS)
    )
    bind.execute(
        company_profiles.update()
        .where(company_profiles.c.auto_ingest_limit.is_(None))
        .values(auto_ingest_limit=25)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    for column_name in [
        "auto_ingest_limit",
        "auto_ingest_enabled",
        "preferred_sam_states",
        "preferred_sam_agencies",
        "preferred_sam_keywords",
        "preferred_sam_naics_codes",
        "preferred_dibbs_fsc_codes",
    ]:
        if _column_exists(inspector, "company_profiles", column_name):
            op.drop_column("company_profiles", column_name)
