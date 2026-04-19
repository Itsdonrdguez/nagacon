"""create company profile tables if missing

Revision ID: f4c5d6e7f8g9
Revises: f3b4c5d6e7f8
Create Date: 2026-04-07 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f4c5d6e7f8g9"
down_revision = "f3b4c5d6e7f8"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "company_profiles"):
        op.create_table(
            "company_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("legal_name", sa.String(), nullable=False),
            sa.Column("uei", sa.String(), nullable=True),
            sa.Column("cage", sa.String(), nullable=True),
            sa.Column("website", sa.String(), nullable=True),
            sa.Column("primary_contact_name", sa.String(), nullable=True),
            sa.Column("primary_contact_email", sa.String(), nullable=True),
            sa.Column("primary_contact_phone", sa.String(), nullable=True),
            sa.Column("address_line1", sa.String(), nullable=True),
            sa.Column("address_line2", sa.String(), nullable=True),
            sa.Column("city", sa.String(), nullable=True),
            sa.Column("state", sa.String(), nullable=True),
            sa.Column("postal_code", sa.String(), nullable=True),
            sa.Column("country", sa.String(), nullable=True),
            sa.Column("naics_codes", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("certifications", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("capability_statement_url", sa.String(), nullable=True),
            sa.Column("core_competencies", sa.Text(), nullable=True),
            sa.Column("differentiators", sa.Text(), nullable=True),
            sa.Column("past_performance_summary", sa.Text(), nullable=True),
            sa.Column("annual_revenue", sa.Float(), nullable=True),
            sa.Column("preferred_dibbs_fsc_codes", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("preferred_sam_naics_codes", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("preferred_sam_keywords", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("preferred_sam_agencies", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("preferred_sam_states", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("auto_ingest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("auto_ingest_limit", sa.Integer(), nullable=True),
            sa.Column("auto_ingest_interval_hours", sa.Integer(), nullable=True),
            sa.Column("last_auto_ingest_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index(op.f("ix_company_profiles_id"), "company_profiles", ["id"], unique=False)
        op.create_index(op.f("ix_company_profiles_organization_id"), "company_profiles", ["organization_id"], unique=False)

    if not _table_exists(inspector, "past_performances"):
        op.create_table(
            "past_performances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_profile_id", sa.Integer(), sa.ForeignKey("company_profiles.id"), nullable=True),
            sa.Column("client_name", sa.String(), nullable=False),
            sa.Column("project_title", sa.String(), nullable=False),
            sa.Column("project_value", sa.Float(), nullable=True),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("naics_code", sa.String(), nullable=True),
            sa.Column("relevance_tags", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index(op.f("ix_past_performances_id"), "past_performances", ["id"], unique=False)
        op.create_index(op.f("ix_past_performances_company_profile_id"), "past_performances", ["company_profile_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "past_performances"):
        op.drop_index(op.f("ix_past_performances_company_profile_id"), table_name="past_performances")
        op.drop_index(op.f("ix_past_performances_id"), table_name="past_performances")
        op.drop_table("past_performances")
    if _table_exists(inspector, "company_profiles"):
        op.drop_index(op.f("ix_company_profiles_organization_id"), table_name="company_profiles")
        op.drop_index(op.f("ix_company_profiles_id"), table_name="company_profiles")
        op.drop_table("company_profiles")
