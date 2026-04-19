"""add submission outcome fields

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bid_submissions", sa.Column("awarded_at", sa.DateTime(), nullable=True))
    op.add_column("bid_submissions", sa.Column("award_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("bid_submissions", sa.Column("winning_vendor_cage", sa.String(length=10), nullable=True))
    op.add_column("bid_submissions", sa.Column("winning_vendor_name", sa.String(length=200), nullable=True))
    op.add_column("bid_submissions", sa.Column("outcome_summary", sa.Text(), nullable=True))
    op.create_index(op.f("ix_bid_submissions_winning_vendor_cage"), "bid_submissions", ["winning_vendor_cage"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bid_submissions_winning_vendor_cage"), table_name="bid_submissions")
    op.drop_column("bid_submissions", "outcome_summary")
    op.drop_column("bid_submissions", "winning_vendor_name")
    op.drop_column("bid_submissions", "winning_vendor_cage")
    op.drop_column("bid_submissions", "award_amount")
    op.drop_column("bid_submissions", "awarded_at")
