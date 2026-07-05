"""Add campaign daily limit.

Revision ID: 20260602_max_per_day
Revises: 722d1018b484
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_max_per_day"
down_revision: Union[str, None] = "722d1018b484"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("max_per_day", sa.Integer(), nullable=True, server_default="100"),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "max_per_day")
