"""Step 8 - Submissions + Opportunity Files (PDFs)"""

from alembic import op
import sqlalchemy as sa


revision = "8c70eabea080"
down_revision = "7a5965bf185d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bid_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("submitted_vendor_cage", sa.String(length=10), nullable=True),
        sa.Column("submitted_vendor_name", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("opportunity_id", name="uq_bid_submissions_opportunity_id"),
    )
    op.create_index("ix_bid_submissions_opportunity_id", "bid_submissions", ["opportunity_id"])
    op.create_index("ix_bid_submissions_status", "bid_submissions", ["status"])
    op.create_index("ix_bid_submissions_submitted_vendor_cage", "bid_submissions", ["submitted_vendor_cage"])

    op.create_table(
        "opportunity_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_type", sa.String(length=30), nullable=False, server_default="PDF"),
        sa.Column("filename", sa.String(length=260), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_opportunity_files_opportunity_id", "opportunity_files", ["opportunity_id"])
    op.create_index("ix_opportunity_files_file_type", "opportunity_files", ["file_type"])


def downgrade() -> None:
    op.drop_index("ix_opportunity_files_file_type", table_name="opportunity_files")
    op.drop_index("ix_opportunity_files_opportunity_id", table_name="opportunity_files")
    op.drop_table("opportunity_files")

    op.drop_index("ix_bid_submissions_submitted_vendor_cage", table_name="bid_submissions")
    op.drop_index("ix_bid_submissions_status", table_name="bid_submissions")
    op.drop_index("ix_bid_submissions_opportunity_id", table_name="bid_submissions")
    op.drop_table("bid_submissions")
