"""add decision fields to opportunities

Revision ID: 9c1f3b7a1d0c
Revises: 573eb6bf14ca
Create Date: 2026-02-23 15:01:29

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c1f3b7a1d0c"
down_revision = "573eb6bf14ca"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("opportunities", sa.Column("decision_status", sa.String(length=16), nullable=False, server_default="NEW"))
    op.add_column("opportunities", sa.Column("decision_note", sa.Text(), nullable=True))
    op.add_column("opportunities", sa.Column("decision_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("opportunities", "decision_updated_at")
    op.drop_column("opportunities", "decision_note")
    op.drop_column("opportunities", "decision_status")
