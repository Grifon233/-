"""add_personal_channel_templates

Revision ID: 20260608_pctpl
Revises: 5af2743b8dc5
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_pctpl"
down_revision: Union[str, None] = "5af2743b8dc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_channel_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("channel_title", sa.String(length=128), nullable=False),
        sa.Column("channel_about", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_channel_templates_id", "personal_channel_templates", ["id"])
    op.create_index("ix_personal_channel_templates_project_id", "personal_channel_templates", ["project_id"])

    op.create_table(
        "personal_channel_template_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("image_path", sa.String(length=512), nullable=True),
        sa.Column("image_filename", sa.String(length=255), nullable=True),
        sa.Column("image_mime_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["template_id"], ["personal_channel_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_channel_template_posts_id", "personal_channel_template_posts", ["id"])
    op.create_index("ix_personal_channel_template_posts_template_id", "personal_channel_template_posts", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_personal_channel_template_posts_template_id", table_name="personal_channel_template_posts")
    op.drop_index("ix_personal_channel_template_posts_id", table_name="personal_channel_template_posts")
    op.drop_table("personal_channel_template_posts")
    op.drop_index("ix_personal_channel_templates_project_id", table_name="personal_channel_templates")
    op.drop_index("ix_personal_channel_templates_id", table_name="personal_channel_templates")
    op.drop_table("personal_channel_templates")
