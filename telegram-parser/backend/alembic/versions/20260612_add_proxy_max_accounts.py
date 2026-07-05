"""add proxies.max_accounts

Revision ID: 20260612_proxy_max_accounts
Revises: 20260611_warmup_assign
Create Date: 2026-06-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260612_proxy_max_accounts"
down_revision: Union[str, None] = "20260611_warmup_assign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("proxies") as batch_op:
        batch_op.add_column(
            sa.Column("max_accounts", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("proxies") as batch_op:
        batch_op.drop_column("max_accounts")
