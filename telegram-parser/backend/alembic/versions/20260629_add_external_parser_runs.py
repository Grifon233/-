"""add_external_parser_runs

Revision ID: 20260629_extparsers
Revises: 20260625_banned_source_ids
Create Date: 2026-06-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_extparsers"
down_revision: Union[str, None] = "20260625_banned_source_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_parser_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("workdir", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_parser_runs_id", "external_parser_runs", ["id"], unique=False
    )
    op.create_index(
        "ix_external_parser_runs_project_id",
        "external_parser_runs",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_external_parser_runs_project_id", table_name="external_parser_runs")
    op.drop_index("ix_external_parser_runs_id", table_name="external_parser_runs")
    op.drop_table("external_parser_runs")
