"""add planned vendor fields to bid submissions

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-04-06 22:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bid_submissions", sa.Column("planned_vendor_quote_id", sa.Integer(), nullable=True))
    op.add_column("bid_submissions", sa.Column("planned_vendor_cage", sa.String(length=10), nullable=True))
    op.add_column("bid_submissions", sa.Column("planned_vendor_name", sa.String(length=200), nullable=True))
    op.create_index("ix_bid_submissions_planned_vendor_quote_id", "bid_submissions", ["planned_vendor_quote_id"], unique=False)
    op.create_index("ix_bid_submissions_planned_vendor_cage", "bid_submissions", ["planned_vendor_cage"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bid_submissions_planned_vendor_cage", table_name="bid_submissions")
    op.drop_index("ix_bid_submissions_planned_vendor_quote_id", table_name="bid_submissions")
    op.drop_column("bid_submissions", "planned_vendor_name")
    op.drop_column("bid_submissions", "planned_vendor_cage")
    op.drop_column("bid_submissions", "planned_vendor_quote_id")
