"""add_personal_channel_template_avatar

Revision ID: 20260609_pctavatar
Revises: 20260609_ctmodes
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_pctavatar"
down_revision: Union[str, None] = "20260609_ctmodes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_channel_templates",
        sa.Column("channel_avatar_mode", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column("personal_channel_templates", sa.Column("channel_avatar_path", sa.String(length=512), nullable=True))
    op.add_column("personal_channel_templates", sa.Column("channel_avatar_filename", sa.String(length=255), nullable=True))
    op.add_column("personal_channel_templates", sa.Column("channel_avatar_mime_type", sa.String(length=128), nullable=True))
    op.alter_column("personal_channel_templates", "channel_avatar_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("personal_channel_templates", "channel_avatar_mime_type")
    op.drop_column("personal_channel_templates", "channel_avatar_filename")
    op.drop_column("personal_channel_templates", "channel_avatar_path")
    op.drop_column("personal_channel_templates", "channel_avatar_mode")
