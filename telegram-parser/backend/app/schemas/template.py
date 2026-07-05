from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class TemplateBase(BaseModel):
    name: str
    content: str

class TemplateCreate(TemplateBase):
    pass

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None

class TemplateInDBBase(TemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MessageTemplate(TemplateInDBBase):
    pass
