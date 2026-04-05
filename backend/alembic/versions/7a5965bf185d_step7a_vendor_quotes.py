"""Step 7A - Vendor quote tracking (manual enrichment)"""

from alembic import op
import sqlalchemy as sa


revision = "7a5965bf185d"
down_revision = "2b6f4c9d8a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("cage", sa.String(length=10), nullable=False, index=True),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("part_number", sa.String(length=80), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="NOT_REQUESTED", index=True),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("opportunity_id", "cage", "part_number", name="uq_vendor_quotes_opp_cage_part"),
    )


def downgrade() -> None:
    op.drop_table("vendor_quotes")
