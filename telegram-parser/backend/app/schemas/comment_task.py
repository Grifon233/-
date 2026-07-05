from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class CommentTaskStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class CommentPolicy(str, Enum):
    DRAFT_ONLY = "draft_only"
    AUTO_PUBLISH = "auto_publish"


class CommentTargetMode(str, Enum):
    CHANNEL_POSTS = "channel_posts"
    GROUP_CONTEXT = "group_context"


class CommentTaskBase(BaseModel):
    name: str
    source_ids: List[int] = []
    target_mode: CommentTargetMode = CommentTargetMode.CHANNEL_POSTS
    target_modes: List[CommentTargetMode] = [CommentTargetMode.CHANNEL_POSTS]
    account_ids: List[int] = []
    comments_per_account: int = 10
    comments_per_source: int = 3
    model: str = "gpt-4o-mini"
    provider: str = "openai"
    topic: Optional[str] = None
    min_delay: int = 60
    max_delay: int = 180
    policy: CommentPolicy = CommentPolicy.DRAFT_ONLY
    moderation_enabled: bool = True


class CommentTaskCreate(CommentTaskBase):
    pass


class CommentTaskUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[CommentTaskStatus] = None
    source_ids: Optional[List[int]] = None
    target_mode: Optional[CommentTargetMode] = None
    target_modes: Optional[List[CommentTargetMode]] = None
    account_ids: Optional[List[int]] = None
    comments_per_account: Optional[int] = None
    comments_per_source: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    topic: Optional[str] = None
    min_delay: Optional[int] = None
    max_delay: Optional[int] = None
    policy: Optional[CommentPolicy] = None
    moderation_enabled: Optional[bool] = None


class CommentTaskResponse(BaseModel):
    id: int
    name: str
    project_id: int
    status: CommentTaskStatus
    policy: CommentPolicy
    source_ids: List[int]
    target_mode: CommentTargetMode
    target_modes: List[CommentTargetMode]
    account_ids: List[int]
    comments_per_account: int
    comments_per_source: int
    model: str
    provider: str
    topic: Optional[str]
    min_delay: int
    max_delay: int
    moderation_enabled: bool
    posts_checked: int
    drafts_created: int
    comments_posted: int
    errors_count: int
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class CommentDraftResponse(BaseModel):
    id: int
    task_id: int
    source_id: int
    account_id: int
    post_id: int
    post_text: str
    draft_text: str
    moderation_flagged: bool
    moderation_reason: Optional[str]
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    published_message_id: Optional[int]
    published_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class CommentLogResponse(BaseModel):
    id: int
    task_id: int
    action: str
    account_id: Optional[int]
    source_id: Optional[int]
    draft_id: Optional[int]
    details: Optional[dict]
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
