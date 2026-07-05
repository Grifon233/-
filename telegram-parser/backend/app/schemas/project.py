from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None


class ProjectResponse(ProjectCreate):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

