"""Add projects and reusable Telegram source lists.

Revision ID: 20260602_projects_sources
Revises: 20260602_max_per_day
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_projects_sources"
down_revision: Union[str, None] = "20260602_max_per_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_project_id(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("project_id", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(f"ix_{table_name}_project_id", table_name, ["project_id"], unique=False)
    op.create_foreign_key(
        f"fk_{table_name}_project_id_projects",
        table_name,
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_id", "projects", ["id"], unique=False)
    op.execute(
        "INSERT INTO projects (id, name, description, is_active) "
        "VALUES (1, 'Основной проект', 'Автоматически создан для существующих данных', true)"
    )

    for table_name in (
        "accounts",
        "proxies",
        "group_tasks",
        "reaction_tasks",
        "ai_settings",
        "contacts",
        "message_templates",
        "campaigns",
        "parsing_tasks",
    ):
        _add_project_id(table_name)

    op.drop_index("ix_contacts_telegram_id", table_name="contacts")
    op.create_index("ix_contacts_telegram_id", "contacts", ["telegram_id"], unique=False)
    op.create_unique_constraint("uq_contacts_project_telegram_id", "contacts", ["project_id", "telegram_id"])

    op.create_table(
        "telegram_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("link", sa.String(length=512), nullable=False),
        sa.Column("normalized_link", sa.String(length=512), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum("CHAT", "GROUP", "CHANNEL", "UNKNOWN", name="telegramsourcetype"),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "normalized_link", name="uq_telegram_sources_project_link"),
    )
    op.create_index("ix_telegram_sources_id", "telegram_sources", ["id"], unique=False)
    op.create_index("ix_telegram_sources_project_id", "telegram_sources", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telegram_sources_project_id", table_name="telegram_sources")
    op.drop_index("ix_telegram_sources_id", table_name="telegram_sources")
    op.drop_table("telegram_sources")
    op.execute("DROP TYPE IF EXISTS telegramsourcetype")

    op.drop_constraint("uq_contacts_project_telegram_id", "contacts", type_="unique")
    op.drop_index("ix_contacts_telegram_id", table_name="contacts")
    op.create_index("ix_contacts_telegram_id", "contacts", ["telegram_id"], unique=True)

    for table_name in (
        "parsing_tasks",
        "campaigns",
        "message_templates",
        "contacts",
        "ai_settings",
        "reaction_tasks",
        "group_tasks",
        "proxies",
        "accounts",
    ):
        op.drop_constraint(f"fk_{table_name}_project_id_projects", table_name, type_="foreignkey")
        op.drop_index(f"ix_{table_name}_project_id", table_name=table_name)
        op.drop_column(table_name, "project_id")

    op.drop_index("ix_projects_id", table_name="projects")
    op.drop_table("projects")
