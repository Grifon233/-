from datetime import date as date_type, datetime, time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class BookingStatus(str, Enum):
    UPCOMING = "upcoming"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class ApiResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    error: Optional[dict] = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None


# Master schemas
class MasterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    avatar_url: Optional[str] = None
    telegram_username: Optional[str] = None
    use_services: bool = False
    interval_minutes: int = Field(default=60, ge=15, le=240)
    schedule_json: dict = Field(default_factory=dict)
    subscription_channel_id: Optional[str] = None
    subscription_text: Optional[str] = None


class MasterCreate(MasterBase):
    pass


class MasterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    avatar_url: Optional[str] = None
    telegram_username: Optional[str] = None
    use_services: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=15, le=240)
    schedule_json: Optional[dict] = None
    subscription_required: Optional[bool] = None
    subscription_channel_id: Optional[str] = None
    subscription_text: Optional[str] = None
    notify_new_bookings: Optional[bool] = None
    notify_reminders: Optional[bool] = None
    reminder_time: Optional[str] = Field(None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekly_report_enabled: Optional[bool] = None
    timezone: Optional[str] = None
    profile_link_warning_dismissed: Optional[bool] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            from backend.timezones import VALID_RUSSIAN_TIMEZONES
            if value not in VALID_RUSSIAN_TIMEZONES:
                raise ValueError("Unsupported Russian timezone")
        return value


class MasterResponse(BaseModel):
    id: int
    name: str
    avatar_url: Optional[str] = None
    telegram_username: Optional[str] = None
    use_services: bool
    interval_minutes: int
    schedule: Optional[dict] = None
    subscription_channel_id: Optional[str] = None
    subscription_text: Optional[str] = None

    class Config:
        from_attributes = True


# Service schemas
class ServiceBase(BaseModel):
    name: Optional[str] = Field("", max_length=100)
    price: Optional[str] = Field("", max_length=50)
    duration_minutes: int = Field(60, ge=15, le=480)
    active: bool = True
    sort_order: int = 0

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return value
        normalized = value.strip()
        if normalized.startswith("-") or not any(char.isdigit() for char in normalized):
            raise ValueError("Цена должна быть неотрицательным числом")
        if any(char not in "0123456789 ,.\u00a0₽руб." for char in normalized.lower()):
            raise ValueError("Некорректный формат цены")
        return value


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    price: Optional[str] = Field(None, min_length=1, max_length=50)
    duration_minutes: Optional[int] = Field(None, ge=15, le=480)
    active: Optional[bool] = None
    sort_order: Optional[int] = None

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Optional[str]) -> Optional[str]:
        return ServiceBase.validate_price(value)


class ServiceResponse(BaseModel):
    id: int
    name: str
    price: str
    duration_minutes: int
    active: bool
    sort_order: int

    class Config:
        from_attributes = True


# Client schemas
class ClientBase(BaseModel):
    telegram_id: int
    name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v:
            # Remove all non-digit characters for validation
            digits = ''.join(c for c in v if c.isdigit())
            if len(digits) < 10:
                raise ValueError("Phone number must have at least 10 digits")
        return v


class ClientCreate(ClientBase):
    pass


class ClientResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    telegram_id: int

    class Config:
        from_attributes = True


# Booking schemas
class BookingBase(BaseModel):
    master_id: int
    client_id: int
    date: date_type
    time: time
    duration_minutes: int = Field(ge=15, le=480)  # 15 минут - 8 часов
    service_ids: list[int] = Field(default_factory=list)
    comment: Optional[str] = Field(None, max_length=500)

    @field_validator("date")
    @classmethod
    def validate_date_not_past(cls, v):
        from datetime import date as date_type
        if v < date_type.today():
            raise ValueError("Cannot book in the past")
        return v

    @field_validator("time")
    @classmethod
    def validate_time_format(cls, v):
        if v.hour < 0 or v.hour > 23 or v.minute not in [0, 15, 30, 45]:
            raise ValueError("Time must be in 15-minute intervals")
        return v

    @model_validator(mode="after")
    def validate_booking_not_in_past(self):
        """Проверяем что запись не в прошлом (дата + время)"""
        booking_datetime = datetime.combine(self.date, self.time)
        if booking_datetime < datetime.now():
            raise ValueError("Cannot book in the past")
        return self


class BookingCreate(BookingBase):
    pass


class BookingResponse(BaseModel):
    id: int
    date: date_type
    time: time
    duration_minutes: int
    status: BookingStatus
    comment: Optional[str] = None
    service_name: Optional[str] = None
    client: Optional[dict] = None
    master: Optional[dict] = None

    class Config:
        from_attributes = True


class CancelBookingRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)
    cancelled_by: Optional[str] = Field(default="client", pattern="^(client|master|admin)$")
    deleted: bool = False


class BookingUpdate(BaseModel):
    status: Optional[BookingStatus] = None
    master_comment: Optional[str] = Field(None, max_length=500)
    date: Optional[date_type] = None
    time: Optional[time] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v and v not in [BookingStatus.UPCOMING, BookingStatus.CONFIRMED,
                           BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW]:
            raise ValueError(f"Invalid status: {v}")
        return v


class BookingResponse(BaseModel):
    id: int
    date: date_type
    time: time
    duration_minutes: int
    status: str
    comment: Optional[str] = None
    services: Optional[list[dict]] = None
    client: Optional[dict] = None
    master: Optional[dict] = None

    class Config:
        from_attributes = True


# Menu Button schemas
class MenuButtonContent(BaseModel):
    active: bool
    content: dict


# Slot schemas
class SlotRequest(BaseModel):
    date: date_type
    duration: int = Field(ge=15, le=480)
    service_ids: Optional[list[int]] = None


class SlotItem(BaseModel):
    time: str
    available: bool
    reason: Optional[str] = None


class SlotsResponse(BaseModel):
    date: date_type
    duration: int
    slots: list[SlotItem]


# Auth schemas
class WebAppAuthRequest(BaseModel):
    initData: str


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class WebAppAuthResponse(BaseModel):
    user: TelegramUser
    session_token: str
    is_registered: bool
    client: Optional[ClientResponse] = None
