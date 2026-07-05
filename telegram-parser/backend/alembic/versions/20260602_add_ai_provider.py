"""Add AI provider selection.

Revision ID: 20260602_ai_provider
Revises: 20260602_projects_sources
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_ai_provider"
down_revision: Union[str, None] = "20260602_projects_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="openai"),
    )


def downgrade() -> None:
    op.drop_column("ai_settings", "provider")

