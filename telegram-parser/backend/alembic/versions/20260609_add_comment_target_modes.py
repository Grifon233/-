"""add_comment_target_modes

Revision ID: 20260609_ctmodes
Revises: 20260609_accnote
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_ctmodes"
down_revision: Union[str, None] = "20260609_accnote"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comment_tasks",
        sa.Column("target_modes", sa.JSON(), nullable=False, server_default='["channel_posts"]'),
    )
    op.alter_column("comment_tasks", "target_modes", server_default=None)


def downgrade() -> None:
    op.drop_column("comment_tasks", "target_modes")
