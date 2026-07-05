"""merge_heads

Revision ID: 20260609_merge_heads
Revises: 20260609_pcbigint, 20260609_draft_status
Create Date: 2026-06-09 16:15:05.379283

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260609_merge_heads'
down_revision: Union[str, None] = ('20260609_pcbigint', '20260609_draft_status')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
