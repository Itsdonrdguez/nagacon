"""add user scope to app settings

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "n8o9p0q1r2s3"
down_revision = "m7n8o9p0q1r2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_app_settings_user_id"), "app_settings", ["user_id"], unique=False)
    op.create_foreign_key(None, "app_settings", "users", ["user_id"], ["id"])
    op.drop_index("ix_app_settings_setting_key", table_name="app_settings")
    op.create_index("ix_app_settings_setting_key", "app_settings", ["setting_key"], unique=False)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_app_settings_scope_key
        ON app_settings (setting_key, COALESCE(organization_id, 0), COALESCE(user_id, 0))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_app_settings_scope_key")
    op.drop_constraint(None, "app_settings", type_="foreignkey")
    op.drop_index(op.f("ix_app_settings_user_id"), table_name="app_settings")
    op.drop_index("ix_app_settings_setting_key", table_name="app_settings")
    op.create_index("ix_app_settings_setting_key", "app_settings", ["setting_key"], unique=True)
    op.drop_column("app_settings", "user_id")
