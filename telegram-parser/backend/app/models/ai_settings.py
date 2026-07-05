"""
AI Settings Model
Настройки AI для аккаунтов: Диалоги, Чаттинг, Комментинг
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Enum as SQLEnum, ForeignKey
from sqlalchemy.sql import func
import enum

from sqlalchemy.orm import relationship

from app.db.base_class import Base


class AIType(str, enum.Enum):
    DIALOGS = "dialogs"
    CHATTING = "chatting"
    COMMENTING = "commenting"


class AISettings(Base):
    __tablename__ = "ai_settings"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    type = Column(SQLEnum(AIType, native_enum=False, values_callable=lambda x: [e.value for e in x]), nullable=False)

    account = relationship("Account")
    project = relationship("Project")
    system_prompt = Column(Text, nullable=False)
    context_depth = Column(Integer, default=10)
    min_delay = Column(Integer, default=5)
    max_delay = Column(Integer, default=60)
    model = Column(String(50), default="gpt-4o-mini")
    provider = Column(String(32), default="openai", nullable=False)
    enabled = Column(Boolean, default=True)
    api_key_id = Column(Integer, nullable=True)  # Link to stored API key
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
