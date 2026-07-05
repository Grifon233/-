"""add_proxy_fields

Revision ID: 371308fc4f83
Revises: 135c569512a8
Create Date: 2026-06-06 23:34:52.676380

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '371308fc4f83'
down_revision: Union[str, None] = '135c569512a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only add the columns we actually need for the new feature
    op.add_column('proxies', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('proxies', sa.Column('external_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('proxies', 'external_id')
    op.drop_column('proxies', 'expires_at')
