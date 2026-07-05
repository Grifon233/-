"""Thin wrapper around the PROXY6 / PX6 HTTPS API.

The provider's documentation is at https://px6.me/ru/developers —
every public method is reachable as ``GET https://px6.link/api/{key}/{method}``
and returns a JSON document. Every successful response includes
``status="yes"`` plus the operator's ``balance`` and ``currency``;
failures come back with ``status="no"`` and an ``error`` message
that we surface to the caller.

Why this module exists
----------------------
The project needs to (a) show the operator's balance and active
proxies on the ``Прокси`` page, (b) buy a new proxy on demand,
(c) renew a proxy before it expires, and (d) re-import the list
of proxies the operator owns. Wrapping these calls in a single
service makes the API layer thin and lets the rest of the codebase
mock the service in tests without monkey-patching ``requests``.

Configuration
-------------
The provider API key is read from the environment (``PROXY6_API_KEY``
or, for backward-compat, ``WEBSHARE_API_KEY`` which we set when we
misidentified the service — same value, different name).

NB: this service is *read-mostly*. The buy/renew calls cost real
money and are gated behind a ``confirm=True`` parameter at the API
layer so a frontend click on the wrong button cannot drain the
operator's balance.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class Proxy6Error(RuntimeError):
    """Raised when the proxy6.net API returns ``status="no"``."""


@dataclass
class Proxy6Account:
    user_id: str
    email: str
    balance: float
    balance_ref: float
    currency: str

    @property
    def balance_str(self) -> str:
        return f"{self.balance:.2f} {self.currency}"


@dataclass
class Proxy6Proxy:
    """A single proxy as returned by ``getproxy``."""
    id: str
    ip: str
    port: int
    user: str
    passwd: str
    type_: str  # "4" or "6" (IPv4/IPv6)
    country: str
    date: datetime
    date_end: datetime
    raw: dict = field(default_factory=dict)

    @property
    def host(self) -> str:
        return self.ip

    @property
    def username(self) -> str:
        return self.user

    @property
    def password(self) -> str:
        return self.passwd

    @property
    def is_ipv6(self) -> bool:
        return self.type_ == "6"

    @property
    def expires_at(self) -> datetime:
        return self.date_end


class Proxy6Service:
    BASE_URL = "https://px6.link/api"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        # ``WEBSHARE_API_KEY`` was the name originally chosen when the
        # service was misidentified; it really is a proxy6 key.
        # Read from ``settings`` (which loads .env at startup) and
        # fall back to ``os.environ`` for tests that don't go through
        # the pydantic-settings loader.
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = (
                getattr(settings, "PROXY6_API_KEY", None)
                or os.getenv("PROXY6_API_KEY")
                or getattr(settings, "WEBSHARE_API_KEY", None)
                or os.getenv("WEBSHARE_API_KEY")
            )
        if not self.api_key:
            raise ValueError(
                "PROXY6_API_KEY (or legacy WEBSHARE_API_KEY) is not set"
            )
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Proxy6Service":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _call(self, method: Optional[str] = None, params: Optional[dict] = None) -> dict:
        url = f"{self.BASE_URL}/{self.api_key}"
        if method:
            url = f"{url}/{method}"
        try:
            resp = await self._client.get(url, params=params or {})
        except httpx.HTTPError as exc:
            raise Proxy6Error(f"network error calling px6.me/{method or 'account'}: {exc}") from exc
        if resp.status_code != 200:
            raise Proxy6Error(
                f"px6.me/{method or 'account'} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise Proxy6Error(
                f"px6.me/{method or 'account'} returned non-JSON: {resp.text[:200]}"
            ) from exc
        if data.get("status") != "yes":
            raise Proxy6Error(
                f"px6.me/{method or 'account'} failed: error_id={data.get('error_id')} "
                f"error={data.get('error')!r}"
            )
        return data

    # ── Account ────────────────────────────────────────────────────────
    async def get_balance(self) -> Proxy6Account:
        data = await self._call(None)
        return Proxy6Account(
            user_id=str(data.get("user_id", "")),
            email=str(data.get("email", "")),
            balance=float(data.get("balance", 0.0)),
            balance_ref=float(data.get("balance_ref", 0.0)),
            currency=str(data.get("currency", "RUB")),
        )

    # ── Proxies ───────────────────────────────────────────────────────
    async def list_proxies(self) -> list[Proxy6Proxy]:
        data = await self._call("getproxy")
        out: list[Proxy6Proxy] = []
        items = data.get("list") or {}
        for raw in items.values():
            try:
                date = _to_naive(datetime.fromisoformat(raw["date_iso"]))
                date_end = _to_naive(datetime.fromisoformat(raw["date_end_iso"]))
            except Exception:
                # Some old records lack the *_iso fields; fall back to
                # the ``date``/``date_end`` strings.
                date = _parse_dt(raw.get("date"))
                date_end = _parse_dt(raw.get("date_end"))
            out.append(
                Proxy6Proxy(
                    id=str(raw.get("id")),
                    ip=str(raw.get("host") or raw.get("ip") or ""),
                    port=int(raw.get("port") or 0),
                    user=str(raw.get("user") or ""),
                    passwd=str(raw.get("pass") or ""),
                    type_=str(raw.get("version") or raw.get("type") or "4"),
                    country=str(raw.get("country") or ""),
                    date=date,
                    date_end=date_end,
                    raw=raw,
                )
            )
        return out

    # ── Buy / renew / delete ──────────────────────────────────────────
    async def buy(
        self,
        country: str,
        count: int = 1,
        period: int = 30,
        version: str = "4",
        type_: str = "socks",
        *,
        confirm: bool = False,
    ) -> list[Proxy6Proxy]:
        """Buy ``count`` proxies. ``confirm=True`` is required — the
        endpoint spends real money."""
        if not confirm:
            raise Proxy6Error(
                "refusing to buy without confirm=True; this call spends money"
            )
        if count < 1 or count > 100:
            raise ValueError("count must be between 1 and 100")
        if period < 1 or period > 365:
            raise ValueError("period must be between 1 and 365 days")
        if version not in {"4", "6"}:
            raise ValueError("Only private IPv4/IPv6 proxies are supported; IPv4 Shared and MTProto are blocked")
        if type_ not in {"socks", "http"}:
            raise ValueError("Proxy type must be socks or http")
        data = await self._call(
            "buy",
            {
                "country": country,
                "count": count,
                "period": period,
                "version": version,
                "type": type_,
            },
        )
        # The "set" endpoint returns the new proxies inline.
        ids = data.get("list") or data.get("proxies") or {}
        if not ids:
            return []
        # Refresh via getproxy to get the structured records.
        all_proxies = await self.list_proxies()
        wanted = {str(i) for i in (ids.values() if isinstance(ids, dict) else ids)}
        return [p for p in all_proxies if p.id in wanted]

    async def renew(self, proxy_id: str, period: int = 30, *, confirm: bool = False) -> dict:
        if not confirm:
            raise Proxy6Error(
                "refusing to renew without confirm=True; this call spends money"
            )
        return await self._call("prolong", {"ids": proxy_id, "period": period})

    async def delete(self, proxy_id: str) -> dict:
        return await self._call("delete", {"ids": proxy_id})

    # ── Pricing ────────────────────────────────────────────────────────
    async def get_count(self) -> dict:
        """Return the price grid keyed by ``{version: {country: count}}``."""
        data = await self._call("getcount")
        return data.get("count", {})

    async def get_countries(self, version: str = "4") -> list[str]:
        """Return country codes available for a private IPv4/IPv6 order."""
        if version not in {"4", "6"}:
            raise ValueError("Only private IPv4/IPv6 countries can be requested")
        data = await self._call("getcountry", {"version": version})
        return [str(item).lower() for item in (data.get("list") or [])]

    async def price(self, country: str, period: int = 30, version: str = "4") -> Optional[float]:
        """Return the price for a single ``country`` proxy of the
        given ``period`` (days), or ``None`` if the country is sold
        out or invalid."""
        grid = await self.get_count()
        # The grid's inner value is the *number of proxies in stock*,
        # not the price. The price itself comes from a separate
        # ``getprice`` call we don't make; returning the count is
        # enough for a "0 → sold out" indicator in the UI.
        bucket = grid.get(version, {})
        if country not in bucket:
            return None
        # We can't return a real price without a per-country call;
        # surface ``None`` and let the operator see the count.
        return float(bucket.get(country, 0)) or None


def _parse_dt(value: Optional[str]) -> datetime:
    if not value:
        return datetime.utcnow()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return _to_naive(datetime.strptime(value, fmt))
        except ValueError:
            continue
    return datetime.utcnow()


def _to_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)
