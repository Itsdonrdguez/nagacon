"""add organizations and org scoping

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-06 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_id"), "organizations", ["id"], unique=False)
    op.create_index(op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="OWNER"),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)

    if "company_profiles" in tables:
        company_columns = {col["name"] for col in inspector.get_columns("company_profiles")}
        if "organization_id" not in company_columns:
            op.add_column("company_profiles", sa.Column("organization_id", sa.Integer(), nullable=True))
        company_indexes = {idx["name"] for idx in inspector.get_indexes("company_profiles")}
        if op.f("ix_company_profiles_organization_id") not in company_indexes:
            op.create_index(op.f("ix_company_profiles_organization_id"), "company_profiles", ["organization_id"], unique=False)

    if "app_settings" in tables:
        setting_columns = {col["name"] for col in inspector.get_columns("app_settings")}
        if "organization_id" not in setting_columns:
            op.add_column("app_settings", sa.Column("organization_id", sa.Integer(), nullable=True))
        setting_indexes = {idx["name"] for idx in inspector.get_indexes("app_settings")}
        if op.f("ix_app_settings_organization_id") not in setting_indexes:
            op.create_index(op.f("ix_app_settings_organization_id"), "app_settings", ["organization_id"], unique=False)

    op.execute(
        sa.text(
            "INSERT INTO organizations (name, slug, is_default) VALUES (:name, :slug, true)"
        ).bindparams(name="Default Organization", slug="default")
    )
    if "company_profiles" in tables:
        op.execute(
            sa.text(
                "UPDATE company_profiles SET organization_id = (SELECT id FROM organizations WHERE slug = :slug LIMIT 1) "
                "WHERE organization_id IS NULL"
            ).bindparams(slug="default")
        )
    if "app_settings" in tables:
        op.execute(
            sa.text(
                "UPDATE app_settings SET organization_id = (SELECT id FROM organizations WHERE slug = :slug LIMIT 1) "
                "WHERE organization_id IS NULL"
            ).bindparams(slug="default")
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_app_settings_organization_id"), table_name="app_settings")
    op.drop_column("app_settings", "organization_id")
    op.drop_index(op.f("ix_company_profiles_organization_id"), table_name="company_profiles")
    op.drop_column("company_profiles", "organization_id")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_organizations_slug"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_id"), table_name="organizations")
    op.drop_table("organizations")
