"""Pydantic schemas for Account.

Public view (``Account``) returns every safe field; encrypted
secrets (``session_string``, ``api_hash``) are never sent to the
browser. ``has_session`` is a boolean derived from the encrypted
blob to let the UI render the auth badge without leaking the
session itself.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.account import AccountSex, AccountStatus


_PHONE_RE = re.compile(r"^\+\d{7,15}$")
_API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _validate_phone(value: str) -> str:
    if not _PHONE_RE.match(value):
        raise ValueError(
            "phone_number must be in E.164 format: '+' followed by 7-15 digits"
        )
    return value


def _validate_api_hash(value: str) -> str:
    if not _API_HASH_RE.match(value):
        raise ValueError("api_hash must be a 32-character hex string from my.telegram.org")
    return value


class AccountCreate(BaseModel):
    # ``phone_number`` is optional for auto-registration: the number is
    # ordered from the SMS service AFTER the row is created, so at
    # creation time it may be a placeholder. A normal manual create
    # still passes a real E.164 number.
    phone_number: Optional[str] = None
    # api_id / api_hash are optional now — when omitted they default to
    # the global Telegram app credentials (settings.TELEGRAM_API_ID/HASH).
    # The operator only needs to fill these in if they have their own
    # my.telegram.org app and want to use it.
    api_id: Optional[int] = Field(default=None, gt=0, lt=2**31, description="Telegram API id from my.telegram.org")
    api_hash: Optional[str] = None
    status: Optional[AccountStatus] = AccountStatus.NEW
    proxy_id: Optional[int] = Field(default=None, gt=0)
    session_string: Optional[str] = None
    tdata_source: Optional[str] = Field(default=None, exclude=True)
    note: Optional[str] = Field(default=None, max_length=255)
    # When ``True`` the account is created as a shell to be filled in by
    # the auto-registration flow (number ordered from SMS service). The
    # phone/api fields may be blank; only a proxy is required.
    auto_register: bool = False
    # Optional explicit smsfast country id (overrides the proxy country).
    sms_country_id: Optional[int] = Field(default=None, ge=0)

    @field_validator("phone_number")
    @classmethod
    def _v_phone_opt(cls, v: Optional[str]) -> Optional[str]:
        return _validate_phone(v) if v else v

    @field_validator("api_hash")
    @classmethod
    def _v_hash_opt(cls, v: Optional[str]) -> Optional[str]:
        return _validate_api_hash(v) if v else v

    @model_validator(mode="after")
    def _validate_combo(self) -> "AccountCreate":
        if self.session_string and not self.proxy_id:
            raise ValueError(
                "proxy_id is required when importing a session_string; "
                "an account cannot be authorized without a proxy."
            )
        if self.auto_register and not self.proxy_id:
            raise ValueError(
                "proxy_id is required for auto-registration; "
                "the number is ordered in the proxy's country."
            )
        if not self.auto_register and not self.phone_number:
            raise ValueError("phone_number is required")
        return self


class AccountUpdate(BaseModel):
    phone_number: Optional[str] = None
    api_id: Optional[int] = Field(default=None, gt=0, lt=2**31)
    api_hash: Optional[str] = None
    status: Optional[AccountStatus] = None
    proxy_id: Optional[int] = Field(default=None, gt=0)
    session_string: Optional[str] = None
    folder: Optional[str] = None
    # Profile fields.
    first_name: Optional[str] = Field(default=None, max_length=64)
    last_name: Optional[str] = Field(default=None, max_length=64)
    bio: Optional[str] = Field(default=None, max_length=70)
    username: Optional[str] = Field(default=None, max_length=32)
    gender: Optional[AccountSex] = None
    personal_channel_id: Optional[int] = Field(default=None, gt=0)
    personal_channel_username: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=255)

    @field_validator("phone_number")
    @classmethod
    def _v_phone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_phone(v) if v else v

    @field_validator("api_hash")
    @classmethod
    def _v_hash(cls, v: Optional[str]) -> Optional[str]:
        return _validate_api_hash(v) if v else v

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{4,31}$", v):
            raise ValueError(
                "username must be 5-32 chars, start with a letter, and contain "
                "only letters, digits and underscores"
            )
        return v


class ProfileWriteRequest(BaseModel):
    """A focused update payload for the profile editor UI.

    The endpoint that accepts this will:
    1. apply the changes to Telegram via Pyrogram
    2. mirror the result into ``accounts`` (first_name, last_name, bio, username)
    3. bump ``last_check_at``

    Avatar upload is a separate endpoint because the file payload
    lives outside JSON.
    """

    first_name: Optional[str] = Field(default=None, max_length=64)
    last_name: Optional[str] = Field(default=None, max_length=64)
    bio: Optional[str] = Field(default=None, max_length=70)
    username: Optional[str] = Field(default=None, max_length=32)

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{4,31}$", v):
            raise ValueError(
                "username must be 5-32 chars, start with a letter, and contain "
                "only letters, digits and underscores"
            )
        return v


class ChannelCreateRequest(BaseModel):
    """Payload to create a personal broadcast channel for an account."""

    title: str = Field(..., min_length=1, max_length=128)
    about: Optional[str] = Field(default=None, max_length=255)
    username: Optional[str] = Field(default=None, max_length=32)
    # When ``True`` the channel is also set as the account's personal
    # channel (calls ``account.updatePersonalChannel``). Default ``True``
    # because that's what 99% of the operator wants when creating a
    # channel from this endpoint.
    set_as_personal: bool = True

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{4,31}$", v):
            raise ValueError(
                "channel username must be 5-32 chars, start with a letter, "
                "and contain only letters, digits and underscores"
            )
        return v


class ChannelPostRequest(BaseModel):
    """Send a single text post to a channel owned by the account."""

    text: str = Field(..., min_length=1, max_length=4096)


class PersonalChannelTemplateRequest(BaseModel):
    """Apply one personal-channel template to multiple accounts."""

    target_account_ids: list[int] = Field(default_factory=list)
    title: str = Field(..., min_length=1, max_length=128)
    about: Optional[str] = Field(default=None, max_length=255)
    posts: list[str] = Field(default_factory=list, max_length=20)
    create_if_missing: bool = True

    @field_validator("target_account_ids")
    @classmethod
    def _v_target_ids(cls, v: list[int]) -> list[int]:
        cleaned = [int(item) for item in v if int(item) > 0]
        if not cleaned:
            raise ValueError("target_account_ids must contain at least one account id")
        return list(dict.fromkeys(cleaned))

    @field_validator("posts")
    @classmethod
    def _v_posts(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        if len(cleaned) > 20:
            raise ValueError("posts supports at most 20 entries per batch")
        for item in cleaned:
            if len(item) > 4096:
                raise ValueError("every post must be 1-4096 characters long")
        return cleaned


class AccountInDBBase(BaseModel):
    """Schema that mirrors the ORM model for read-back.

    Excludes ``session_string`` / ``api_hash`` but exposes
    ``has_session`` so the UI can render the auth badge.
    """

    id: int
    project_id: int
    phone_number: str
    status: Optional[AccountStatus] = AccountStatus.NEW
    proxy_id: Optional[int] = None
    proxy_country: Optional[str] = None
    note: Optional[str] = None
    folder: str = "new"
    has_session: bool = False

    # GGR / warmup bookkeeping
    warmup_level: int = 0
    warmup_phase: Optional[int] = None
    warmup_locked: bool = False
    daily_dm_count: int = 0
    total_messages_sent: int = 0
    daily_limit_used: float = 0.0
    health_score: Optional[int] = None
    health_factors: Optional[dict] = None

    # Profile fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    username: Optional[str] = None
    avatar_path: Optional[str] = None
    # Exposed to the UI as ``gender`` to match the existing
    # frontend type. The DB column is also named ``gender``.
    gender: AccountSex = AccountSex.UNKNOWN
    personal_channel_id: Optional[int] = None
    personal_channel_username: Optional[str] = None
    # Which personal-channel template is currently applied (None = none).
    personal_channel_template_id: Optional[int] = None

    # Lifecycle
    created_at: Optional[Union[datetime, str]] = None
    last_active: Optional[Union[datetime, str]] = None
    last_check_at: Optional[Union[datetime, str]] = None

    @model_validator(mode="before")
    @classmethod
    def _populate_has_session(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "has_session" not in data:
                data["has_session"] = bool(data.get("session_string"))
        else:
            session = getattr(data, "session_string", None)
            data_dict = {
                "id": data.id,
                "project_id": data.project_id,
                "phone_number": data.phone_number,
                "status": data.status,
                "proxy_id": data.proxy_id,
                "proxy_country": getattr(getattr(data, "proxy", None), "country", None),
                "note": getattr(data, "note", None),
                "folder": data.folder,
                "warmup_level": data.warmup_level,
                "warmup_phase": getattr(data, "warmup_phase", None),
                "warmup_locked": bool(getattr(data, "warmup_locked", False)),
                "daily_dm_count": data.daily_dm_count,
                "total_messages_sent": data.total_messages_sent,
                "daily_limit_used": data.daily_limit_used,
                "health_score": data.health_score,
                "health_factors": data.health_factors,
                "first_name": getattr(data, "first_name", None),
                "last_name": getattr(data, "last_name", None),
                "bio": getattr(data, "bio", None),
                "username": getattr(data, "username", None),
                "avatar_path": getattr(data, "avatar_path", None),
                "gender": getattr(data, "sex", AccountSex.UNKNOWN),
                "personal_channel_id": getattr(data, "personal_channel_id", None),
                "personal_channel_username": getattr(data, "personal_channel_username", None),
                "personal_channel_template_id": getattr(data, "personal_channel_template_id", None),
                "created_at": data.created_at,
                "last_active": data.last_active,
                "last_check_at": data.last_check_at,
                "has_session": bool(session),
            }
            return data_dict
        return data

    class Config:
        from_attributes = True


class Account(AccountInDBBase):
    pass
