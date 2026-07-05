from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class GroupTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

class GroupTaskCreate(BaseModel):
    account_id: int
    groups: List[str]
    delay_min: int = 30
    delay_max: int = 120

class GroupTaskResponse(BaseModel):
    id: int
    account_id: int
    account_name: str
    groups: List[str]
    status: GroupTaskStatus
    groups_joined: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class GroupTaskCreateResponse(BaseModel):
    task_id: int
    status: str
    message: str
