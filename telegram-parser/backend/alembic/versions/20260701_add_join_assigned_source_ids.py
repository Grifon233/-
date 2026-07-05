"""add_join_assigned_source_ids

Per-account slice of the global join pool: only this account is
responsible for joining these sources (no overlap with other accounts).

Revision ID: 20260701_join_assigned
Revises: 20260701_join_sessions
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260701_join_assigned"
down_revision: Union[str, None] = "20260701_join_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "join_assigned_source_ids",
            JSONB,
            nullable=True,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "join_assigned_source_ids")
