from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.telegram_source import TelegramSourceType


class TelegramSourceBulkCreate(BaseModel):
    links: List[str] = Field(..., min_length=1, max_length=5000)
    source_type: TelegramSourceType = TelegramSourceType.UNKNOWN
    group_id: Optional[int] = None


class TelegramSourceGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=512)


class TelegramSourceGroupCreate(TelegramSourceGroupBase):
    pass


class TelegramSourceGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=512)


class TelegramSourceResponse(BaseModel):
    id: int
    project_id: int
    group_id: Optional[int]
    link: str
    normalized_link: str
    source_type: TelegramSourceType
    title: Optional[str]
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TelegramSourceGroupResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class TelegramSourceBulkResponse(BaseModel):
    created: int
    skipped: int
    invalid: List[str]


class TelegramSourceDeduplicateResponse(BaseModel):
    removed: int


class TelegramSourceDiagnoseRequest(BaseModel):
    group_id: Optional[int] = None
    account_id: Optional[int] = None
    delete_invalid: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


class TelegramSourceDiagnoseResponse(BaseModel):
    checked: int
    updated: int
    deleted: int
    failed: int
    counts: dict[str, int]
    errors: List[str] = []
