"""merge migration heads

Revision ID: b02bf7da9296
Revises: 8c70eabea080, c8f1d2ab9011
Create Date: 2026-03-10 11:46:35.993928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b02bf7da9296'
down_revision: Union[str, Sequence[str], None] = ('8c70eabea080', 'c8f1d2ab9011')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
