from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from app.models.campaign import CampaignStatus

class CampaignBase(BaseModel):
    name: str
    template_id: int
    min_delay: Optional[int] = 30
    max_delay: Optional[int] = 120
    max_per_day: Optional[int] = 100

class CampaignCreate(CampaignBase):
    pass

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    template_id: Optional[int] = None
    status: Optional[CampaignStatus] = None
    min_delay: Optional[int] = None
    max_delay: Optional[int] = None
    max_per_day: Optional[int] = None

class MessageLogSchema(BaseModel):
    id: int
    campaign_id: int
    account_id: int
    contact_id: int
    status: str
    error_message: Optional[str]
    sent_at: datetime

    class Config:
        from_attributes = True

class CampaignInDBBase(CampaignBase):
    id: int
    status: CampaignStatus
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True

class Campaign(CampaignInDBBase):
    pass

class CampaignWithStats(Campaign):
    total_contacts: int = 0
    sent_count: int = 0
    failed_count: int = 0
