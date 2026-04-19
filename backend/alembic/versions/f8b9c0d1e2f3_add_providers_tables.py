"""add providers tables

Revision ID: f8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-14 17:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "providers"):
        op.create_table(
            "providers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("company_name", sa.String(length=240), nullable=False),
            sa.Column("cage", sa.String(length=20), nullable=True),
            sa.Column("uei", sa.String(length=40), nullable=True),
            sa.Column("website", sa.String(length=500), nullable=True),
            sa.Column("contact_name", sa.String(length=160), nullable=True),
            sa.Column("email", sa.String(length=240), nullable=True),
            sa.Column("phone", sa.String(length=80), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=40), server_default="active", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(op.f("ix_providers_id"), "providers", ["id"], unique=False)
        op.create_index(op.f("ix_providers_organization_id"), "providers", ["organization_id"], unique=False)
        op.create_index(op.f("ix_providers_company_name"), "providers", ["company_name"], unique=False)
        op.create_index(op.f("ix_providers_cage"), "providers", ["cage"], unique=False)
        op.create_index(op.f("ix_providers_uei"), "providers", ["uei"], unique=False)
        op.create_index(op.f("ix_providers_status"), "providers", ["status"], unique=False)

    if not _table_exists(inspector, "provider_items"):
        op.create_table(
            "provider_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=True),
            sa.Column("fsc", sa.String(length=10), nullable=True),
            sa.Column("nomenclature", sa.String(length=300), nullable=True),
            sa.Column("relationship_type", sa.String(length=60), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=False),
            sa.Column("source_url", sa.String(length=700), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("provider_id", "nsn", "relationship_type", "source", name="uq_provider_item_provider_nsn_type_source"),
        )
        op.create_index(op.f("ix_provider_items_id"), "provider_items", ["id"], unique=False)
        op.create_index(op.f("ix_provider_items_provider_id"), "provider_items", ["provider_id"], unique=False)
        op.create_index(op.f("ix_provider_items_nsn"), "provider_items", ["nsn"], unique=False)
        op.create_index(op.f("ix_provider_items_fsc"), "provider_items", ["fsc"], unique=False)
        op.create_index(op.f("ix_provider_items_nomenclature"), "provider_items", ["nomenclature"], unique=False)
        op.create_index(op.f("ix_provider_items_relationship_type"), "provider_items", ["relationship_type"], unique=False)
        op.create_index(op.f("ix_provider_items_source"), "provider_items", ["source"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "provider_items"):
        op.drop_index(op.f("ix_provider_items_source"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_relationship_type"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_nomenclature"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_fsc"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_nsn"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_provider_id"), table_name="provider_items")
        op.drop_index(op.f("ix_provider_items_id"), table_name="provider_items")
        op.drop_table("provider_items")
    if _table_exists(inspector, "providers"):
        op.drop_index(op.f("ix_providers_status"), table_name="providers")
        op.drop_index(op.f("ix_providers_uei"), table_name="providers")
        op.drop_index(op.f("ix_providers_cage"), table_name="providers")
        op.drop_index(op.f("ix_providers_company_name"), table_name="providers")
        op.drop_index(op.f("ix_providers_organization_id"), table_name="providers")
        op.drop_index(op.f("ix_providers_id"), table_name="providers")
        op.drop_table("providers")
