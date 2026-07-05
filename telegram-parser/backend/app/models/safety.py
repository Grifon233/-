from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, JSON, Text, Index
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.db.base_class import Base


class SourceType(str, enum.Enum):
    CHAT = "chat"
    CHANNEL = "channel"
    GROUP = "group"


class DraftStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class SourceAllowlist(Base):
    """Разрешённые источники для действий."""
    __tablename__ = "source_allowlist"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(Enum(SourceType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    source_id = Column(String, nullable=False)
    source_title = Column(String, nullable=True)
    consent_verified = Column(Boolean, default=False)
    consent_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project")


class AccountActionLimit(Base):
    """Дневные лимиты для аккаунтов."""
    __tablename__ = "account_action_limits"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    dm_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    reaction_count = Column(Integer, default=0)
    join_count = Column(Integer, default=0)
    last_action_at = Column(DateTime, nullable=True)

    account = relationship("Account")

    __table_args__ = (
        Index('ix_account_date', 'account_id', 'date', unique=True),
    )


class SafetyDraft(Base):
    """Черновики нейрокомментинга (Safety Manager)."""
    __tablename__ = "safety_drafts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(String, nullable=False)
    post_id = Column(Integer, nullable=False)
    context = Column(Text, nullable=False)
    draft = Column(Text, nullable=False)
    status = Column(Enum(DraftStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]), default=DraftStatus.PENDING)
    moderation_result = Column(JSON, nullable=True)
    risk_flags = Column(JSON, nullable=True)
    prompt_version = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_message_id = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project")
    account = relationship("Account")


class ActionLog(Base):
    """Журнал всех действий."""
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    action_type = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=True)
    source_type = Column(String, nullable=True)
    result = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    project = relationship("Project")
    account = relationship("Account")