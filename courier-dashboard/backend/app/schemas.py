"""Формы данных, которыми обмениваются части системы (см. docs/02)."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestMessage(BaseModel):
    """Сырое сообщение от сборщика (collector -> backend)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    source_chat: str = Field(min_length=1, max_length=255)
    message_id: int = Field(gt=0)
    message_link: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=10000)
    ts: datetime
    city: str | None = Field(default=None, max_length=100)

    @field_validator("ts")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts must include timezone")
        return value


class Quote(BaseModel):
    """Цитата из чата, привязанная к улице (показывается по тапу)."""
    text: str
    link: str
    ts: datetime


class Street(BaseModel):
    """Занятая улица для карты."""
    id: str
    city: str
    street: str
    active: bool
    quotes: list[Quote]
    expires_at: datetime
    geometry: dict | None = None
