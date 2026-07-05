from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.db.base_class import Base

class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    template_id = Column(Integer, ForeignKey("message_templates.id", ondelete="RESTRICT"), nullable=False)
    status = Column(Enum(CampaignStatus, values_callable=lambda x: [e.value for e in x]), default=CampaignStatus.DRAFT)
    
    # Settings
    min_delay = Column(Integer, default=30) # seconds
    max_delay = Column(Integer, default=120) # seconds
    max_per_day = Column(Integer, default=100)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    template = relationship("MessageTemplate")
    logs = relationship("MessageLog", back_populates="campaign", cascade="all, delete-orphan")
    # Per-campaign recipient tracking. See app/models/campaign_recipient.py
    # for the rationale — replaces the broken global ``Contact.is_processed``
    # approach.
    recipients = relationship(
        "CampaignRecipient",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    status = Column(String, nullable=False) # e.g., "sent", "failed", "flood_wait"
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    
    campaign = relationship("Campaign", back_populates="logs")
    account = relationship("Account")
    contact = relationship("Contact")
