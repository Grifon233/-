"""add accounts.personal_channel_template_id

Binds an account to the personal-channel template that was applied to
it. Enables: showing the chosen template in the UI (instead of
"Без шаблона") and auto-resyncing every account when its template is
edited.

Revision ID: 20260609_pc_tpl_id
Revises: 20260609_merge_heads
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_pc_tpl_id"
down_revision: Union[str, None] = "20260609_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("personal_channel_template_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_accounts_personal_channel_template_id",
        "accounts",
        "personal_channel_templates",
        ["personal_channel_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_accounts_personal_channel_template_id", "accounts", type_="foreignkey"
    )
    op.drop_column("accounts", "personal_channel_template_id")
