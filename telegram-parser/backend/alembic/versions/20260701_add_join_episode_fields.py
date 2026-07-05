"""add_join_episode_fields

Adds per-account daily-progress tracking for the progressive channel-joining
scheduler, so a day's quota is spread across several randomly-timed bursts
("episodes") instead of one long uninterrupted run:

* join_day_date       — "YYYYMMDD" of the day the progress counters below
                         apply to; a mismatch means "new day, reset".
* join_day_target      — how many joins this account should do today
                         (picked from JOIN_PROGRESSION when the day rolls over).
* join_day_joined      — how many it has done today so far.
* join_next_episode_at — earliest time this account may run its next burst;
                          randomized after every episode so accounts drift
                          apart instead of firing in lockstep.

Revision ID: 20260701_join_episodes
Revises: 20260701_join_assigned
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260701_join_episodes"
down_revision: Union[str, None] = "20260701_join_assigned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("join_day_date", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("join_day_target", sa.Integer(), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("join_day_joined", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "accounts",
        sa.Column("join_next_episode_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "join_next_episode_at")
    op.drop_column("accounts", "join_day_joined")
    op.drop_column("accounts", "join_day_target")
    op.drop_column("accounts", "join_day_date")
