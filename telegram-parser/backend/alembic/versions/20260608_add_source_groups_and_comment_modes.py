"""add_source_groups_and_comment_modes

Revision ID: 20260608_srcgrp
Revises: 20260608_pctpl
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_srcgrp"
down_revision: Union[str, None] = "20260608_pctpl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_source_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_telegram_source_groups_project_name"),
    )
    op.create_index("ix_telegram_source_groups_id", "telegram_source_groups", ["id"])
    op.create_index("ix_telegram_source_groups_project_id", "telegram_source_groups", ["project_id"])

    op.add_column("telegram_sources", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_index("ix_telegram_sources_group_id", "telegram_sources", ["group_id"])
    op.create_foreign_key(
        "fk_telegram_sources_group_id",
        "telegram_sources",
        "telegram_source_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )

    comment_target_mode = sa.Enum(
        "channel_posts",
        "group_context",
        name="commenttargetmode",
    )
    comment_target_mode.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "comment_tasks",
        sa.Column(
            "target_mode",
            comment_target_mode,
            nullable=False,
            server_default="channel_posts",
        ),
    )
    op.alter_column("comment_tasks", "target_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("comment_tasks", "target_mode")
    sa.Enum(name="commenttargetmode").drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("fk_telegram_sources_group_id", "telegram_sources", type_="foreignkey")
    op.drop_index("ix_telegram_sources_group_id", table_name="telegram_sources")
    op.drop_column("telegram_sources", "group_id")

    op.drop_index("ix_telegram_source_groups_project_id", table_name="telegram_source_groups")
    op.drop_index("ix_telegram_source_groups_id", table_name="telegram_source_groups")
    op.drop_table("telegram_source_groups")
