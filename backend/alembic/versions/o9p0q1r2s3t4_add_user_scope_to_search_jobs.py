"""add user scope to search jobs

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-04-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "o9p0q1r2s3t4"
down_revision = "n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_jobs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_search_jobs_user_id"), "search_jobs", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_search_jobs_user_id_users",
        "search_jobs",
        "users",
        ["user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_search_jobs_user_id_users", "search_jobs", type_="foreignkey")
    op.drop_index(op.f("ix_search_jobs_user_id"), table_name="search_jobs")
    op.drop_column("search_jobs", "user_id")
