"""add_closed_source_type

Revision ID: 20260609_closedsrc
Revises: 20260609_cstates
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260609_closedsrc"
down_revision: Union[str, None] = "20260609_cstates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE telegramsourcetype ADD VALUE IF NOT EXISTS 'closed'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values without recreating the type.
    # Keeping the value is safer than rewriting historical rows.
    pass
