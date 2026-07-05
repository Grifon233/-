"""add chat_search, comments and tgstat_search to parsingtype enum

Revision ID: 20260606_add_parsingtype_chat_search
Revises:
Create Date: 2026-06-06

Adds the ``chat_search``, ``comments`` and ``tgstat_search`` values to
the ``parsingtype`` PostgreSQL enum so the parser can persist
those task types. All three values are harmless on SQLite because
SQLAlchemy ``Enum`` there doesn't enforce the value list at the
storage level — but on PostgreSQL the enum is part of the column
type, so we have to ``ALTER TYPE`` explicitly.

Without this migration the backend returns::

    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum parsingtype: "chat_search"

when an operator submits a chat-search task.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260606_parsing_chat"
down_revision = "20260604_recipients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ``IF NOT EXISTS`` keeps the migration idempotent on
        # databases where the values were already added by a
        # hotfix script.
        op.execute("ALTER TYPE parsingtype ADD VALUE IF NOT EXISTS 'comments'")
        op.execute("ALTER TYPE parsingtype ADD VALUE IF NOT EXISTS 'chat_search'")
        op.execute("ALTER TYPE parsingtype ADD VALUE IF NOT EXISTS 'tgstat_search'")


def downgrade() -> None:
    # PostgreSQL doesn't support DROP VALUE for an enum — the
    # standard rollback is to rename the type, recreate it
    # without the values, and migrate the column. We keep the
    # downgrade a no-op so a botched downgrade doesn't leave the
    # schema in a broken state; the operator can recreate the
    # database if they really need to drop the new values.
    pass
