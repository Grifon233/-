"""add accounts.banned_source_ids

Revision ID: 20260625_banned_source_ids
Revises: 20260612_proxy_max_accounts
Create Date: 2026-06-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260625_banned_source_ids"
down_revision: Union[str, None] = "20260612_proxy_max_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "banned_source_ids",
                JSONB(),
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("banned_source_ids")
