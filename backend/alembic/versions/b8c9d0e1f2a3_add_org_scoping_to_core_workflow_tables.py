"""add org scoping to core workflow tables

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-06 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _default_org_subquery():
    return "(SELECT id FROM organizations WHERE slug = 'default' LIMIT 1)"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def ensure_org_column(table_name: str, index_name: str):
        if table_name not in tables:
            return
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if "organization_id" not in columns:
            op.add_column(table_name, sa.Column("organization_id", sa.Integer(), nullable=True))
        indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["organization_id"], unique=False)
        op.execute(sa.text(f"UPDATE {table_name} SET organization_id = {_default_org_subquery()} WHERE organization_id IS NULL"))

    ensure_org_column("opportunities", op.f("ix_opportunities_organization_id"))
    ensure_org_column("pipeline_items", op.f("ix_pipeline_items_organization_id"))
    ensure_org_column("workspace_artifacts", op.f("ix_workspace_artifacts_organization_id"))
    ensure_org_column("workspace_tasks", op.f("ix_workspace_tasks_organization_id"))
    ensure_org_column("opportunity_files", op.f("ix_opportunity_files_organization_id"))
    ensure_org_column("vendor_leads", op.f("ix_vendor_leads_organization_id"))
    ensure_org_column("vendor_quotes", op.f("ix_vendor_quotes_organization_id"))
    ensure_org_column("vendor_opportunity_matches", op.f("ix_vendor_opportunity_matches_organization_id"))

    op.execute(
        sa.text(
            f"INSERT INTO users (email, full_name, role, organization_id, is_active) "
            f"SELECT 'owner@nagacon.local', 'Default Owner', 'OWNER', {_default_org_subquery()}, true "
            f"WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'owner@nagacon.local')"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_vendor_opportunity_matches_organization_id"), table_name="vendor_opportunity_matches")
    op.drop_column("vendor_opportunity_matches", "organization_id")
    op.drop_index(op.f("ix_vendor_quotes_organization_id"), table_name="vendor_quotes")
    op.drop_column("vendor_quotes", "organization_id")
    op.drop_index(op.f("ix_vendor_leads_organization_id"), table_name="vendor_leads")
    op.drop_column("vendor_leads", "organization_id")
    op.drop_index(op.f("ix_opportunity_files_organization_id"), table_name="opportunity_files")
    op.drop_column("opportunity_files", "organization_id")
    op.drop_index(op.f("ix_workspace_tasks_organization_id"), table_name="workspace_tasks")
    op.drop_column("workspace_tasks", "organization_id")
    op.drop_index(op.f("ix_workspace_artifacts_organization_id"), table_name="workspace_artifacts")
    op.drop_column("workspace_artifacts", "organization_id")
    op.drop_index(op.f("ix_pipeline_items_organization_id"), table_name="pipeline_items")
    op.drop_column("pipeline_items", "organization_id")
    op.drop_index(op.f("ix_opportunities_organization_id"), table_name="opportunities")
    op.drop_column("opportunities", "organization_id")
