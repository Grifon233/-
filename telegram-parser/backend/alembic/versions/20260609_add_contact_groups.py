"""add_contact_groups

Revision ID: 20260609_ctgroups
Revises: 20260609_closedsrc
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_ctgroups"
down_revision: Union[str, None] = "20260609_closedsrc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_contact_groups_project_name"),
    )
    op.create_index("ix_contact_groups_id", "contact_groups", ["id"])
    op.create_index("ix_contact_groups_project_id", "contact_groups", ["project_id"])
    op.add_column("contacts", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_index("ix_contacts_group_id", "contacts", ["group_id"])
    op.create_foreign_key(
        "fk_contacts_group_id",
        "contacts",
        "contact_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_contacts_group_id", "contacts", type_="foreignkey")
    op.drop_index("ix_contacts_group_id", table_name="contacts")
    op.drop_column("contacts", "group_id")
    op.drop_index("ix_contact_groups_project_id", table_name="contact_groups")
    op.drop_index("ix_contact_groups_id", table_name="contact_groups")
    op.drop_table("contact_groups")
