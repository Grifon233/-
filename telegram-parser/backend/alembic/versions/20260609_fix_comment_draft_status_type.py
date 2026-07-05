"""fix_comment_draft_status_type

Revision ID: 20260609_draft_status
Revises: 20260609_ctmodes
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_draft_status"
down_revision: Union[str, None] = "20260609_ctmodes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "comment_drafts",
        "status",
        existing_type=sa.Enum(
            "draft",
            "running",
            "paused",
            "completed",
            "failed",
            "stopped",
            name="commenttaskstatus",
        ),
        type_=sa.String(length=32),
        postgresql_using="status::text",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "comment_drafts",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.Enum(
            "draft",
            "running",
            "paused",
            "completed",
            "failed",
            "stopped",
            name="commenttaskstatus",
        ),
        postgresql_using="status::commenttaskstatus",
        existing_nullable=True,
    )
