"""add nsn catalog tables

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "nsn_catalog_import_runs"):
        op.create_table(
            "nsn_catalog_import_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_name", sa.String(length=80), nullable=False),
            sa.Column("source_version", sa.String(length=80), nullable=True),
            sa.Column("source_file", sa.String(length=700), nullable=True),
            sa.Column("status", sa.String(length=40), server_default="pending", nullable=False),
            sa.Column("rows_seen", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rows_imported", sa.Integer(), server_default="0", nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_nsn_catalog_import_runs_id"), "nsn_catalog_import_runs", ["id"], unique=False)
        op.create_index(op.f("ix_nsn_catalog_import_runs_source_name"), "nsn_catalog_import_runs", ["source_name"], unique=False)
        op.create_index(op.f("ix_nsn_catalog_import_runs_source_version"), "nsn_catalog_import_runs", ["source_version"], unique=False)
        op.create_index(op.f("ix_nsn_catalog_import_runs_status"), "nsn_catalog_import_runs", ["status"], unique=False)

    if not _table_exists(inspector, "nsn_master"):
        op.create_table(
            "nsn_master",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=False),
            sa.Column("compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("fsc", sa.String(length=4), nullable=False),
            sa.Column("niin", sa.String(length=9), nullable=False),
            sa.Column("item_name", sa.String(length=300), nullable=True),
            sa.Column("item_name_code", sa.String(length=20), nullable=True),
            sa.Column("demil_code", sa.String(length=20), nullable=True),
            sa.Column("criticality_code", sa.String(length=20), nullable=True),
            sa.Column("public_data_status", sa.String(length=40), server_default="public", nullable=False),
            sa.Column("source_name", sa.String(length=80), server_default="manual", nullable=False),
            sa.Column("source_version", sa.String(length=80), nullable=True),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_nsn_master_id"), "nsn_master", ["id"], unique=False)
        op.create_index(op.f("ix_nsn_master_nsn"), "nsn_master", ["nsn"], unique=True)
        op.create_index(op.f("ix_nsn_master_compact_nsn"), "nsn_master", ["compact_nsn"], unique=True)
        op.create_index(op.f("ix_nsn_master_fsc"), "nsn_master", ["fsc"], unique=False)
        op.create_index(op.f("ix_nsn_master_niin"), "nsn_master", ["niin"], unique=False)
        op.create_index(op.f("ix_nsn_master_item_name"), "nsn_master", ["item_name"], unique=False)
        op.create_index(op.f("ix_nsn_master_item_name_code"), "nsn_master", ["item_name_code"], unique=False)
        op.create_index(op.f("ix_nsn_master_demil_code"), "nsn_master", ["demil_code"], unique=False)
        op.create_index(op.f("ix_nsn_master_criticality_code"), "nsn_master", ["criticality_code"], unique=False)
        op.create_index(op.f("ix_nsn_master_public_data_status"), "nsn_master", ["public_data_status"], unique=False)
        op.create_index(op.f("ix_nsn_master_source_name"), "nsn_master", ["source_name"], unique=False)
        op.create_index(op.f("ix_nsn_master_source_version"), "nsn_master", ["source_version"], unique=False)

    if not _table_exists(inspector, "nsn_references"):
        op.create_table(
            "nsn_references",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=False),
            sa.Column("compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("fsc", sa.String(length=4), nullable=True),
            sa.Column("niin", sa.String(length=9), nullable=True),
            sa.Column("cage", sa.String(length=20), nullable=True),
            sa.Column("company_name", sa.String(length=300), nullable=True),
            sa.Column("part_number", sa.String(length=160), nullable=True),
            sa.Column("reference_type", sa.String(length=80), nullable=True),
            sa.Column("relationship_type", sa.String(length=80), nullable=True),
            sa.Column("source_name", sa.String(length=80), nullable=False),
            sa.Column("source_version", sa.String(length=80), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("compact_nsn", "cage", "part_number", "source_name", name="uq_nsn_reference_nsn_cage_part_source"),
        )
        for column in ["id", "nsn", "compact_nsn", "fsc", "niin", "cage", "company_name", "part_number", "reference_type", "relationship_type", "source_name", "source_version"]:
            op.create_index(op.f(f"ix_nsn_references_{column}"), "nsn_references", [column], unique=False)

    if not _table_exists(inspector, "nsn_interchangeability"):
        op.create_table(
            "nsn_interchangeability",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=False),
            sa.Column("compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("related_nsn", sa.String(length=40), nullable=False),
            sa.Column("related_compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("relationship_type", sa.String(length=80), nullable=False),
            sa.Column("order_of_use", sa.String(length=40), nullable=True),
            sa.Column("source_name", sa.String(length=80), nullable=False),
            sa.Column("source_version", sa.String(length=80), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("compact_nsn", "related_compact_nsn", "relationship_type", "source_name", name="uq_nsn_interchangeability_pair_type_source"),
        )
        for column in ["id", "nsn", "compact_nsn", "related_nsn", "related_compact_nsn", "relationship_type", "source_name", "source_version"]:
            op.create_index(op.f(f"ix_nsn_interchangeability_{column}"), "nsn_interchangeability", [column], unique=False)

    if not _table_exists(inspector, "nsn_evidence"):
        op.create_table(
            "nsn_evidence",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=False),
            sa.Column("compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("claim_type", sa.String(length=80), nullable=False),
            sa.Column("claim_value", sa.String(length=500), nullable=True),
            sa.Column("source_name", sa.String(length=80), nullable=False),
            sa.Column("source_url", sa.String(length=700), nullable=True),
            sa.Column("source_version", sa.String(length=80), nullable=True),
            sa.Column("matched_by", sa.String(length=80), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ["id", "nsn", "compact_nsn", "claim_type", "source_name", "source_version", "matched_by"]:
            op.create_index(op.f(f"ix_nsn_evidence_{column}"), "nsn_evidence", [column], unique=False)

    if not _table_exists(inspector, "nsn_intelligence_snapshots"):
        op.create_table(
            "nsn_intelligence_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nsn", sa.String(length=40), nullable=False),
            sa.Column("compact_nsn", sa.String(length=13), nullable=False),
            sa.Column("source_scope", sa.String(length=80), server_default="catalog", nullable=False),
            sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("confidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ["id", "nsn", "compact_nsn", "source_scope", "generated_at"]:
            op.create_index(op.f(f"ix_nsn_intelligence_snapshots_{column}"), "nsn_intelligence_snapshots", [column], unique=False)


def downgrade() -> None:
    for table_name, columns in [
        ("nsn_intelligence_snapshots", ["generated_at", "source_scope", "compact_nsn", "nsn", "id"]),
        ("nsn_evidence", ["matched_by", "source_version", "source_name", "claim_type", "compact_nsn", "nsn", "id"]),
        ("nsn_interchangeability", ["source_version", "source_name", "relationship_type", "related_compact_nsn", "related_nsn", "compact_nsn", "nsn", "id"]),
        ("nsn_references", ["source_version", "source_name", "relationship_type", "reference_type", "part_number", "company_name", "cage", "niin", "fsc", "compact_nsn", "nsn", "id"]),
        ("nsn_master", ["source_version", "source_name", "public_data_status", "criticality_code", "demil_code", "item_name_code", "item_name", "niin", "fsc", "compact_nsn", "nsn", "id"]),
        ("nsn_catalog_import_runs", ["status", "source_version", "source_name", "id"]),
    ]:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, table_name):
            continue
        for column in columns:
            op.drop_index(op.f(f"ix_{table_name}_{column}"), table_name=table_name)
        op.drop_table(table_name)
