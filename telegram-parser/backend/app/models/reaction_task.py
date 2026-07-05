"""
ReactionTask Model
Модель для хранения задач массовых реакций
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.db.base_class import Base


class ReactionTaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ReactionTask(Base):
    __tablename__ = "reaction_tasks"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    channels = Column(Text, nullable=False)  # JSON array as string
    selected_reactions = Column(Text, nullable=False)  # JSON array as string
    reactions_per_day = Column(Integer, default=200)
    posts_per_channel = Column(Integer, default=10)
    reactions_used = Column(Integer, default=0)
    status = Column(
        SQLEnum(ReactionTaskStatus, values_callable=lambda x: [e.value for e in x]),
        default=ReactionTaskStatus.PENDING,
        nullable=False
    )
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    project = relationship("Project")

    def get_channels(self) -> list:
        import json
        return json.loads(self.channels) if self.channels else []

    def set_channels(self, channels: list):
        import json
        self.channels = json.dumps(channels)

    def get_reactions(self) -> list:
        import json
        return json.loads(self.selected_reactions) if self.selected_reactions else []

    def set_reactions(self, reactions: list):
        import json
        self.selected_reactions = json.dumps(reactions)
