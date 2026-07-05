from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.models.external_parser import ExternalParserStatus, ExternalParserType


class ExternalParserRunBase(BaseModel):
    parser: ExternalParserType
    account_id: Optional[int] = None
    config: Optional[Dict[str, Any]] = None


class ExternalParserRunCreate(ExternalParserRunBase):
    pass


class ExternalParserRunInDBBase(ExternalParserRunBase):
    id: int
    status: ExternalParserStatus
    result_count: int
    file_path: Optional[str] = None
    workdir: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExternalParserRun(ExternalParserRunInDBBase):
    pass
