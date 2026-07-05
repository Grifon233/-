"""merge_heads

Revision ID: 135c569512a8
Revises: 93a6b185d4cc, 20260606_add_parsingtype_chat_search
Create Date: 2026-06-06 23:33:32.571180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '135c569512a8'
down_revision: Union[str, None] = ('93a6b185d4cc', '20260606_parsing_chat')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
