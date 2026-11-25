"""Формы данных, которыми обмениваются части системы."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestMessage(BaseModel):
    """Сырое сообщение от сборщика (collector -> backend)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    source_chat: str = Field(min_length=1, max_length=255)
    message_id: int = Field(gt=0, strict=True)
    message_link: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=10000)
    ts: datetime
    city: str | None = Field(default=None, max_length=100)

    @field_validator("ts", mode="before")
    @classmethod
    def require_datetime(cls, value):
        if isinstance(value, str) and not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ]", value):
            raise ValueError("ts must be an ISO 8601 datetime")
        if not isinstance(value, (str, datetime)):
            raise ValueError("ts must be an ISO 8601 datetime")
        return value

    @field_validator("ts")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts must include timezone")
        try:
            return value.astimezone(timezone.utc)
        except OverflowError as exc:
            raise ValueError("ts is outside the supported UTC range") from exc

    @field_validator("message_link")
    @classmethod
    def validate_message_link(cls, value: str) -> str:
        if re.fullmatch(r"chat:-?[0-9]+/[1-9][0-9]*", value):
            return value
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("message_link must reference a Telegram message")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() not in {"t.me", "telegram.me"}
            or not re.fullmatch(r"/[A-Za-z0-9_]+/[1-9][0-9]*/?", parsed.path)
            or parsed.query or parsed.fragment
        ):
            raise ValueError("message_link must reference a Telegram message")
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
