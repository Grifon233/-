"""add_comment_source_states

Revision ID: 20260609_cstates
Revises: 20260608_srcgrp
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260609_cstates"
down_revision: Union[str, None] = "20260608_srcgrp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    state_status = postgresql.ENUM(
        "pending",
        "in_progress",
        "done",
        "join_requested",
        "failed",
        "skipped",
        name="commentsourcestatestatus",
        create_type=False,
    )
    state_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "comment_task_source_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("status", state_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["telegram_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["comment_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "source_id", name="uq_comment_task_source_state"),
    )
    op.create_index("ix_comment_task_source_states_id", "comment_task_source_states", ["id"])
    op.create_index("ix_comment_task_source_states_task_id", "comment_task_source_states", ["task_id"])
    op.create_index("ix_comment_task_source_states_source_id", "comment_task_source_states", ["source_id"])
    op.create_index("ix_comment_task_source_states_account_id", "comment_task_source_states", ["account_id"])
    op.create_index("ix_comment_task_source_states_status", "comment_task_source_states", ["status"])


def downgrade() -> None:
    op.drop_index("ix_comment_task_source_states_status", table_name="comment_task_source_states")
    op.drop_index("ix_comment_task_source_states_account_id", table_name="comment_task_source_states")
    op.drop_index("ix_comment_task_source_states_source_id", table_name="comment_task_source_states")
    op.drop_index("ix_comment_task_source_states_task_id", table_name="comment_task_source_states")
    op.drop_index("ix_comment_task_source_states_id", table_name="comment_task_source_states")
    op.drop_table("comment_task_source_states")
    sa.Enum(name="commentsourcestatestatus").drop(op.get_bind(), checkfirst=True)
