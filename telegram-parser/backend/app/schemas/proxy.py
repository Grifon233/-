"""Pydantic schemas for Proxy."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProxyBase(BaseModel):
    scheme: Optional[str] = "socks5"
    host: str = Field(..., min_length=3)
    port: int = Field(..., ge=1, le=65535)
    username: Optional[str] = None
    is_active: Optional[bool] = True
    # Vendor / lifecycle fields
    source: Optional[str] = "manual"
    vendor_name: Optional[str] = None
    vendor_proxy_id: Optional[str] = None
    country: Optional[str] = Field(default=None, max_length=8)
    expires_at: Optional[datetime] = None
    note: Optional[str] = None
    use_for_accounts: bool = True
    max_accounts: Optional[int] = 3

    @field_validator("scheme")
    @classmethod
    def _v_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower()
        if v not in {"socks5", "socks4", "http", "https"}:
            raise ValueError(f"unsupported proxy scheme: {v!r}")
        return v


class ProxyCreate(ProxyBase):
    password: Optional[str] = None


class ProxyUpdate(BaseModel):
    scheme: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    source: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_proxy_id: Optional[str] = None
    country: Optional[str] = None
    expires_at: Optional[datetime] = None
    note: Optional[str] = None
    use_for_accounts: Optional[bool] = None
    max_accounts: Optional[int] = None

    @field_validator("scheme")
    @classmethod
    def _v_scheme(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower()
        if v not in {"socks5", "socks4", "http", "https"}:
            raise ValueError(f"unsupported proxy scheme: {v!r}")
        return v


class ProxyBulkPasteRequest(BaseModel):
    """Body for POST /proxies/paste — the operator pastes a blob of
    proxies, one per line, in any of the supported formats:

        socks5://user:pass@1.2.3.4:1080
        1.2.3.4:1080
        1.2.3.4:1080:user:pass
        socks5://user:pass@[2001:db8::1]:1080

    The endpoint returns a structured report.
    """
    text: str = Field(..., min_length=1, max_length=200_000)
    default_source: str = "pasted"
    default_vendor: Optional[str] = None


class Proxy(ProxyBase):
    id: int
    project_id: int
    last_checked_at: Optional[datetime] = None
    response_time_ms: Optional[int] = None
    account_count: int = 0

    class Config:
        from_attributes = True
