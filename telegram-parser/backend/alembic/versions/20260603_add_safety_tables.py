"""add_safety_tables

Revision ID: 20260603_add_safety_tables
Revises: 20260602_projects_sources
Create Date: 2026-06-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260603_add_safety_tables"
down_revision: Union[str, None] = "20260602_projects_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # source_allowlist
    op.create_table(
        "source_allowlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Enum("CHAT", "CHANNEL", "GROUP", name="sourcetype"), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_title", sa.String(), nullable=True),
        sa.Column("consent_verified", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("consent_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_allowlist_id", "source_allowlist", ["id"], unique=False)
    op.create_index("ix_source_allowlist_project_id", "source_allowlist", ["project_id"], unique=False)

    # account_action_limits
    op.create_table(
        "account_action_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("dm_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("comment_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("reaction_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("join_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("last_action_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_action_limits_id", "account_action_limits", ["id"], unique=False)
    op.create_index("ix_account_action_limits_account_id", "account_action_limits", ["account_id"], unique=False)
    op.create_index("ix_account_date", "account_action_limits", ["account_id", "date"], unique=True)

    # safety_drafts
    op.create_table(
        "safety_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "APPROVED", "REJECTED", "PUBLISHED", name="draftstatus"), nullable=True, server_default="PENDING"),
        sa.Column("moderation_result", sa.JSON(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("model_used", sa.String(), nullable=True),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_message_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_safety_drafts_id", "safety_drafts", ["id"], unique=False)
    op.create_index("ix_safety_drafts_project_id", "safety_drafts", ["project_id"], unique=False)

    # action_logs
    op.create_table(
        "action_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_logs_id", "action_logs", ["id"], unique=False)
    op.create_index("ix_action_logs_action_type", "action_logs", ["action_type"], unique=False)
    op.create_index("ix_action_logs_timestamp", "action_logs", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_action_logs_timestamp", table_name="action_logs")
    op.drop_index("ix_action_logs_action_type", table_name="action_logs")
    op.drop_index("ix_action_logs_id", table_name="action_logs")
    op.drop_table("action_logs")

    op.drop_index("ix_safety_drafts_project_id", table_name="safety_drafts")
    op.drop_index("ix_safety_drafts_id", table_name="safety_drafts")
    op.drop_table("safety_drafts")

    op.drop_index("ix_account_date", table_name="account_action_limits")
    op.drop_index("ix_account_action_limits_account_id", table_name="account_action_limits")
    op.drop_index("ix_account_action_limits_id", table_name="account_action_limits")
    op.drop_table("account_action_limits")

    op.drop_index("ix_source_allowlist_project_id", table_name="source_allowlist")
    op.drop_index("ix_source_allowlist_id", table_name="source_allowlist")
    op.drop_table("source_allowlist")

    op.execute("DROP TYPE IF EXISTS draftstatus")
    op.execute("DROP TYPE IF EXISTS sourcetype")