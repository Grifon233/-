"""Per-campaign recipient tracking.

The previous design relied on the global ``Contact.is_processed`` flag,
which permanently excluded a contact from any future campaign after one
successful send. This made "send a follow-up wave" impossible without
manual SQL surgery. ``CampaignRecipient`` decouples campaign progress
from the contact itself: each (campaign, contact) pair gets its own
row, status and attempt counter.

This is a 2026-06-02 audit follow-up (CRIT-005).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class RecipientStatus(str, enum.Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    FAILED_RETRY = "failed_retry"
    SKIPPED = "skipped"


class CampaignRecipient(Base):
    __tablename__ = "campaign_recipients"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id = Column(
        Integer,
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    status = Column(
        Enum(RecipientStatus),
        default=RecipientStatus.PENDING,
        nullable=False,
    )
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # A contact can only appear once per campaign. This constraint is
    # what makes "send the same contact twice" impossible, and gives us
    # idempotency when ``run_campaign`` is re-enqueued.
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "contact_id", name="uq_campaign_recipient_per_campaign"
        ),
        Index("ix_recipient_campaign_status", "campaign_id", "status"),
        Index("ix_recipient_next_retry", "next_retry_at"),
    )

    campaign = relationship("Campaign", back_populates="recipients")
    contact = relationship("Contact")
    account = relationship("Account")
