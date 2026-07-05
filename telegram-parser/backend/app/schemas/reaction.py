from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class ReactionTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

class ReactionTaskCreate(BaseModel):
    account_id: int
    channels: List[str]
    reactions: List[str] = ["👍", "❤️", "🔥"]
    reactions_per_day: int = 200
    posts_per_channel: int = 10

class ReactionTaskUpdate(BaseModel):
    channels: Optional[List[str]] = None
    reactions: Optional[List[str]] = None
    reactions_per_day: Optional[int] = None
    posts_per_channel: Optional[int] = None
    status: Optional[ReactionTaskStatus] = None

class ReactionStats(BaseModel):
    total_reactions: int
    reactions_today: int
    active_tasks: int
    accounts_reacting: int

class ReactionTaskResponse(BaseModel):
    id: int
    account_id: int
    account_name: str
    channels: List[str]
    reactions_used: int
    status: ReactionTaskStatus
    reactions_per_day: int
    selected_reactions: List[str]
    posts_per_channel: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class ReactionTaskCreateResponse(BaseModel):
    task_id: int
    status: str
    message: str