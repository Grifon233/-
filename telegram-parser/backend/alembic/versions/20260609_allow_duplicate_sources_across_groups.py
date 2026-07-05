"""allow_duplicate_sources_across_groups

Revision ID: 20260609_srcgroups
Revises: 20260609_pctavatar
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_srcgroups"
down_revision: Union[str, None] = "20260609_pctavatar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_telegram_sources_project_link", "telegram_sources", type_="unique")
    op.create_unique_constraint(
        "uq_telegram_sources_project_group_link",
        "telegram_sources",
        ["project_id", "group_id", "normalized_link"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_telegram_sources_project_group_link", "telegram_sources", type_="unique")
    op.create_unique_constraint(
        "uq_telegram_sources_project_link",
        "telegram_sources",
        ["project_id", "normalized_link"],
    )
