"""add_join_session_fields

Adds join_session_count and join_last_session_at to accounts table
for the progressive channel-joining scheduler.

Revision ID: 20260701_join_sessions
Revises: 20260629_extparsers
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_join_sessions"
down_revision: Union[str, None] = "20260629_extparsers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("join_session_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "accounts",
        sa.Column("join_last_session_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "join_last_session_at")
    op.drop_column("accounts", "join_session_count")
