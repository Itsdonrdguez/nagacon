"""expand company profile fields

Revision ID: d4e5f6a7b8c9
Revises: b02bf7da9296
Create Date: 2026-04-05 19:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "b02bf7da9296"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    op.add_column("company_profiles", sa.Column("website", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("primary_contact_name", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("primary_contact_email", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("primary_contact_phone", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("address_line1", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("address_line2", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("city", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("state", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("postal_code", sa.String(), nullable=True))
    op.add_column("company_profiles", sa.Column("country", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "company_profiles"):
        return

    op.drop_column("company_profiles", "country")
    op.drop_column("company_profiles", "postal_code")
    op.drop_column("company_profiles", "state")
    op.drop_column("company_profiles", "city")
    op.drop_column("company_profiles", "address_line2")
    op.drop_column("company_profiles", "address_line1")
    op.drop_column("company_profiles", "primary_contact_phone")
    op.drop_column("company_profiles", "primary_contact_email")
    op.drop_column("company_profiles", "primary_contact_name")
    op.drop_column("company_profiles", "website")
