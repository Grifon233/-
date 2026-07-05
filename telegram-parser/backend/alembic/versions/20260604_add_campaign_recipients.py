"""add_campaign_recipients

Revision ID: 20260604_recipients
Revises: 20260603_add_safety_tables
Create Date: 2026-06-04

Adds the per-campaign recipient table that lets us re-use contacts
across multiple campaigns. The old design used the global
``Contact.is_processed`` flag, which permanently excluded a contact
from any future campaign after one successful send.

See app/models/campaign_recipient.py for the rationale.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260604_recipients"
down_revision: Union[str, None] = "20260603_add_safety_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_recipients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "SENDING",
                "SENT",
                "FAILED",
                "FAILED_RETRY",
                "SKIPPED",
                name="recipientstatus",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "contact_id", name="uq_campaign_recipient_per_campaign"
        ),
    )
    op.create_index(
        "ix_recipient_campaign_status",
        "campaign_recipients",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_recipient_next_retry",
        "campaign_recipients",
        ["next_retry_at"],
    )
    op.create_index(
        "ix_campaign_recipients_campaign_id", "campaign_recipients", ["campaign_id"]
    )
    op.create_index(
        "ix_campaign_recipients_contact_id", "campaign_recipients", ["contact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_recipients_contact_id", table_name="campaign_recipients")
    op.drop_index("ix_campaign_recipients_campaign_id", table_name="campaign_recipients")
    op.drop_index("ix_recipient_next_retry", table_name="campaign_recipients")
    op.drop_index("ix_recipient_campaign_status", table_name="campaign_recipients")
    op.drop_table("campaign_recipients")
    # Drop the enum type explicitly for PostgreSQL.
    sa.Enum(name="recipientstatus").drop(op.get_bind(), checkfirst=True)
