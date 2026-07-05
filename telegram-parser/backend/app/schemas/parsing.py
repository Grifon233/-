from typing import Optional, Any, Dict
from pydantic import BaseModel
from datetime import datetime
from app.models.parsing import ParsingType, ParsingStatus

class ParsingTaskBase(BaseModel):
    type: ParsingType
    target: str
    params: Optional[Dict[str, Any]] = None
    account_id: Optional[int] = None

class ParsingTaskCreate(ParsingTaskBase):
    pass

class ParsingTaskUpdate(BaseModel):
    status: Optional[ParsingStatus] = None
    result_count: Optional[int] = None
    file_path: Optional[str] = None
    finished_at: Optional[datetime] = None

class ParsingTaskInDBBase(ParsingTaskBase):
    id: int
    status: ParsingStatus
    result_count: int
    file_path: Optional[str]
    created_at: datetime
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True

class ParsingTask(ParsingTaskInDBBase):
    pass
