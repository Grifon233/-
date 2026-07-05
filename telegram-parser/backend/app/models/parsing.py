from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
import enum
from datetime import datetime
from app.db.base_class import Base

class ParsingType(str, enum.Enum):
    USERS = "users"
    MESSAGES = "messages"
    CHANNELS = "channels"
    COMMENTS = "comments"
    CHAT_SEARCH = "chat_search"
    TGSTAT_SEARCH = "tgstat_search"

class ParsingStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class ParsingTask(Base):
    __tablename__ = "parsing_tasks"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ParsingType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    status = Column(Enum(ParsingStatus, values_callable=lambda x: [e.value for e in x]), default=ParsingStatus.PENDING)
    
    target = Column(String, nullable=False) # e.g., "@group_username" or "keyword"
    params = Column(JSON, nullable=True) # e.g., {"limit": 1000}
    
    result_count = Column(Integer, default=0)
    file_path = Column(String, nullable=True) # Path to CSV/Excel result
    
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, default=1, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    
    account = relationship("Account")
