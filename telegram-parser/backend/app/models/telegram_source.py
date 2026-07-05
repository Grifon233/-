import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint

from app.db.base_class import Base


class TelegramSourceType(str, enum.Enum):
    CHAT = "chat"
    GROUP = "group"
    CHANNEL = "channel"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class TelegramSource(Base):
    __tablename__ = "telegram_sources"
    __table_args__ = (
        UniqueConstraint("project_id", "group_id", "normalized_link", name="uq_telegram_sources_project_group_link"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("telegram_source_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    link = Column(String(512), nullable=False)
    normalized_link = Column(String(512), nullable=False)
    source_type = Column(Enum(TelegramSourceType, values_callable=lambda x: [e.value for e in x]), default=TelegramSourceType.UNKNOWN, nullable=False)
    title = Column(String(255), nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TelegramSourceGroup(Base):
    __tablename__ = "telegram_source_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_telegram_source_groups_project_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
