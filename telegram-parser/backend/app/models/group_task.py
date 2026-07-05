"""
GroupTask Model
Модель для хранения задач вступления в группы
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.db.base_class import Base


class GroupTaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class GroupTask(Base):
    __tablename__ = "group_tasks"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    groups = Column(Text, nullable=False)  # JSON array as string
    status = Column(
        SQLEnum(GroupTaskStatus, values_callable=lambda x: [e.value for e in x]),
        default=GroupTaskStatus.PENDING,
        nullable=False
    )
    groups_joined = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    project = relationship("Project")

    def get_groups(self) -> list:
        import json
        return json.loads(self.groups) if self.groups else []

    def set_groups(self, groups: list):
        import json
        self.groups = json.dumps(groups)
