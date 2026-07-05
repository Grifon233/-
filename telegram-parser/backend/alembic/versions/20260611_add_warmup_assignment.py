"""add accounts.warmup_assignment and joined_source_ids

Revision ID: 20260611_warmup_assign
Revises: 20260609_pc_tpl_id
Create Date: 2026-06-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260611_warmup_assign"
down_revision: Union[str, None] = "20260609_pc_tpl_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("warmup_assignment", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("warmup_assignment")
