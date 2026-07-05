"""add_account_note

Revision ID: 20260609_accnote
Revises: 20260609_ctgroups
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_accnote"
down_revision: Union[str, None] = "20260609_ctgroups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("note", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "note")
