"""add price history table

Revision ID: f9c0d1e2f3g4
Revises: f8b9c0d1e2f3
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa


revision = "f9c0d1e2f3g4"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("nsn", sa.String(length=40), nullable=True),
        sa.Column("award_id", sa.String(length=120), nullable=True),
        sa.Column("award_date", sa.String(length=40), nullable=True),
        sa.Column("supplier_name", sa.String(length=240), nullable=True),
        sa.Column("cage", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("total_price", sa.Float(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("source_label", sa.String(length=120), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["source_file_id"], ["opportunity_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_id", "source_file_id", "award_id", "cage", "unit_price", name="uq_price_history_opp_file_award_cage_price"),
    )
    op.create_index(op.f("ix_price_history_id"), "price_history", ["id"], unique=False)
    op.create_index(op.f("ix_price_history_opportunity_id"), "price_history", ["opportunity_id"], unique=False)
    op.create_index(op.f("ix_price_history_organization_id"), "price_history", ["organization_id"], unique=False)
    op.create_index(op.f("ix_price_history_source_file_id"), "price_history", ["source_file_id"], unique=False)
    op.create_index(op.f("ix_price_history_nsn"), "price_history", ["nsn"], unique=False)
    op.create_index(op.f("ix_price_history_award_id"), "price_history", ["award_id"], unique=False)
    op.create_index(op.f("ix_price_history_supplier_name"), "price_history", ["supplier_name"], unique=False)
    op.create_index(op.f("ix_price_history_cage"), "price_history", ["cage"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_price_history_cage"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_supplier_name"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_award_id"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_nsn"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_source_file_id"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_organization_id"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_opportunity_id"), table_name="price_history")
    op.drop_index(op.f("ix_price_history_id"), table_name="price_history")
    op.drop_table("price_history")
