"""Step 7B - vendor leads extracted from approved sources"""

from alembic import op
import sqlalchemy as sa


revision = "c8f1d2ab9011"
down_revision = "7a5965bf185d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="APPROVED_SOURCE"),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("cage", sa.String(length=10), nullable=True),
        sa.Column("part_number", sa.String(length=80), nullable=True),
        sa.Column("nsn", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="NEW"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_approved_source", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("opportunity_id", "cage", "company_name", "part_number", name="uq_vendor_leads_opp_cage_company_part"),
    )
    op.create_index("ix_vendor_leads_opportunity_id", "vendor_leads", ["opportunity_id"])
    op.create_index("ix_vendor_leads_cage", "vendor_leads", ["cage"])
    op.create_index("ix_vendor_leads_nsn", "vendor_leads", ["nsn"])
    op.create_index("ix_vendor_leads_source_type", "vendor_leads", ["source_type"])
    op.create_index("ix_vendor_leads_status", "vendor_leads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_vendor_leads_status", table_name="vendor_leads")
    op.drop_index("ix_vendor_leads_source_type", table_name="vendor_leads")
    op.drop_index("ix_vendor_leads_nsn", table_name="vendor_leads")
    op.drop_index("ix_vendor_leads_cage", table_name="vendor_leads")
    op.drop_index("ix_vendor_leads_opportunity_id", table_name="vendor_leads")
    op.drop_table("vendor_leads")
