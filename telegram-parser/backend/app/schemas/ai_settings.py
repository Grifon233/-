from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class AIType(str, Enum):
    DIALOGS = "dialogs"
    CHATTING = "chatting"
    COMMENTING = "commenting"

class AISettingsBase(BaseModel):
    account_id: int
    type: AIType
    system_prompt: str
    context_depth: int = 10
    min_delay: int = 5
    max_delay: int = 60
    model: str = "gpt-4o-mini"
    provider: str = "openai"
    enabled: bool = True

class AISettingsCreate(AISettingsBase):
    pass

class AISettingsUpdate(BaseModel):
    system_prompt: Optional[str] = None
    context_depth: Optional[int] = None
    min_delay: Optional[int] = None
    max_delay: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    enabled: Optional[bool] = None

class AISettingsResponse(BaseModel):
    id: int
    account_id: int
    account_name: str
    type: AIType
    enabled: bool
    system_prompt: str
    context_depth: int
    min_delay: int
    max_delay: int
    model: str
    provider: str
    created_at: datetime

    class Config:
        from_attributes = True

class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime

class ConversationSummary(BaseModel):
    conversation_key: str
    message_count: int
    messages: List[ConversationMessage]
    is_active: bool

class PromptPreset(BaseModel):
    id: str
    name: str
    prompt: str
