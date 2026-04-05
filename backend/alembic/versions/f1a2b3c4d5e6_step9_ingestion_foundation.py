"""step9 ingestion foundation

Revision ID: f1a2b3c4d5e6
Revises: b02bf7da9296
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f1a2b3c4d5e6'
down_revision = 'b02bf7da9296'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('opportunities', sa.Column('source_opportunity_id', sa.String(length=120), nullable=True))
    op.add_column('opportunities', sa.Column('sub_agency', sa.String(length=200), nullable=True))
    op.add_column('opportunities', sa.Column('office', sa.String(length=200), nullable=True))
    op.add_column('opportunities', sa.Column('place_of_performance', sa.String(length=200), nullable=True))
    op.add_column('opportunities', sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_opportunities_source_opportunity_id', 'opportunities', ['source_opportunity_id'], unique=False)
    op.create_unique_constraint('uq_opportunity_source_id', 'opportunities', ['source', 'source_opportunity_id'])

    op.add_column('opportunity_files', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column('opportunity_files', sa.Column('parsed_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('opportunity_files', 'parsed_metadata')
    op.drop_column('opportunity_files', 'extracted_text')

    op.drop_constraint('uq_opportunity_source_id', 'opportunities', type_='unique')
    op.drop_index('ix_opportunities_source_opportunity_id', table_name='opportunities')
    op.drop_column('opportunities', 'raw_payload')
    op.drop_column('opportunities', 'place_of_performance')
    op.drop_column('opportunities', 'office')
    op.drop_column('opportunities', 'sub_agency')
    op.drop_column('opportunities', 'source_opportunity_id')
