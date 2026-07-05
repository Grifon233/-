from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from app.models.safety import SourceType, DraftStatus


# SourceAllowlist schemas
class SourceAllowlistCreate(BaseModel):
    source_type: SourceType
    source_id: str
    source_title: Optional[str] = None
    project_id: int


class SourceAllowlistResponse(SourceAllowlistCreate):
    id: int
    consent_verified: bool
    consent_expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# AccountActionLimit schemas
class AccountLimitResponse(BaseModel):
    account_id: int
    date: datetime
    dm_count: int
    comment_count: int
    reaction_count: int
    join_count: int
    limits: dict = {
        "dm": 50,
        "comment": 30,
        "reaction": 100,
        "join": 5,
    }

    class Config:
        from_attributes = True


# SafetyDraft schemas (НЕ CommentDraft!)
class SafetyDraftCreate(BaseModel):
    project_id: int
    account_id: int
    source_id: str
    post_id: int
    context: str
    draft: str
    prompt_version: Optional[str] = None
    model_used: Optional[str] = None


class SafetyDraftResponse(SafetyDraftCreate):
    id: int
    status: DraftStatus
    moderation_result: Optional[dict]
    risk_flags: Optional[List[str]]
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    published_at: Optional[datetime]
    error: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class DraftModerateRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    edited_draft: Optional[str] = None


# ActionLog schemas
class ActionLogResponse(BaseModel):
    id: int
    project_id: int
    account_id: Optional[int]
    action_type: str
    source_id: Optional[str]
    source_type: Optional[str]
    result: Optional[str]
    error: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


# Rate limit check
class RateLimitCheck(BaseModel):
    action_type: str
    account_id: int


class RateLimitResult(BaseModel):
    allowed: bool
    remaining: int
    ttl: int
    current: int
    limit: int