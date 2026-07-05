from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ContactBase(BaseModel):
    group_id: Optional[int] = None
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    source: Optional[str] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(BaseModel):
    group_id: Optional[int] = None
    telegram_id: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    is_processed: Optional[bool] = None

class ContactInDBBase(ContactBase):
    id: int
    is_processed: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Contact(ContactInDBBase):
    pass


class ContactGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=512)


class ContactGroupCreate(ContactGroupBase):
    pass


class ContactGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=512)


class ContactGroupResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ContactBulkCreate(BaseModel):
    group_id: Optional[int] = None
    values: List[str] = Field(..., min_length=1, max_length=10000)


class ContactBulkResponse(BaseModel):
    created: int
    skipped: int
    invalid: List[str]
