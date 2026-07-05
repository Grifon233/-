"""add_proxy_refinement_fields

Revision ID: 9e78122f974d
Revises: 371308fc4f83
Create Date: 2026-06-06 23:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9e78122f974d'
down_revision: Union[str, None] = '371308fc4f83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('proxies', sa.Column('use_for_accounts', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('proxies', sa.Column('country', sa.String(length=2), nullable=True))
    # Reset is_active to None for existing proxies to indicate they haven't been checked yet
    op.execute("UPDATE proxies SET is_active = NULL")


def downgrade() -> None:
    op.drop_column('proxies', 'country')
    op.drop_column('proxies', 'use_for_accounts')
