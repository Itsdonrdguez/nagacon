"""add closed solicitation processing records

Revision ID: p1q2r3s4t5u6
Revises: o9p0q1r2s3t4
Create Date: 2026-05-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "p1q2r3s4t5u6"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "closed_solicitation_processing_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_file_id", sa.Integer(), nullable=True),
        sa.Column("solicitation_number", sa.String(length=120), nullable=True),
        sa.Column("nsn", sa.String(length=40), nullable=True),
        sa.Column("part_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("vendor_names", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cage_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pricing_history_notes", sa.Text(), nullable=True),
        sa.Column("original_source_file_name", sa.String(length=260), nullable=True),
        sa.Column("original_source_url", sa.Text(), nullable=True),
        sa.Column("local_path_before_deletion", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("deletion_timestamp", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_file_id"], ["opportunity_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "opportunity_id",
            "file_sha256",
            name="uq_closed_solicitation_processing_org_opp_hash",
        ),
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_id"),
        "closed_solicitation_processing_records",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_organization_id"),
        "closed_solicitation_processing_records",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_opportunity_id"),
        "closed_solicitation_processing_records",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_opportunity_file_id"),
        "closed_solicitation_processing_records",
        ["opportunity_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_solicitation_number"),
        "closed_solicitation_processing_records",
        ["solicitation_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_nsn"),
        "closed_solicitation_processing_records",
        ["nsn"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_file_sha256"),
        "closed_solicitation_processing_records",
        ["file_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_closed_solicitation_processing_records_extraction_status"),
        "closed_solicitation_processing_records",
        ["extraction_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_closed_solicitation_processing_records_extraction_status"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_file_sha256"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_nsn"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_solicitation_number"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_opportunity_file_id"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_opportunity_id"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_organization_id"), table_name="closed_solicitation_processing_records")
    op.drop_index(op.f("ix_closed_solicitation_processing_records_id"), table_name="closed_solicitation_processing_records")
    op.drop_table("closed_solicitation_processing_records")
