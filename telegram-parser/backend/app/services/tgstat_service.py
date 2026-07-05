"""TGStat (https://api.tgstat.ru) client.

This is a small async wrapper around the public TGStat REST API.
We use it as a **no-Telegram-account-required** alternative to
``chat_search``: TGStat has indexed 2.7M+ channels and groups
through its own Telegram user-accounts, so the operator can
discover and filter public chats without burning their own
accounts.

API key
    Register at https://tgstat.ru/my/profile and pick the
    ``API Stat`` plan (S or above) to enable ``channels/search``.
    Put the token in ``TGSTAT_API_TOKEN`` in ``.env``.

Pricing
    See https://tgstat.ru/api/stat — billed per unique channel.
    The free tier only works for channels you own.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TGStatError(RuntimeError):
    """Raised when TGStat returns an error response."""


class TGStatService:
    """Thin async wrapper around https://api.tgstat.ru.

    The service holds no per-request state. A single shared
    :class:`httpx.AsyncClient` is created lazily and re-used so
    connection setup is amortised across calls.
    """

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self._token = token or settings.TGSTAT_API_TOKEN
        self._base_url = (base_url or settings.TGSTAT_API_BASE).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": "tg-comb/1.0 (TGStat-client)"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search_channels(
        self,
        q: Optional[str] = None,
        *,
        category: Optional[str] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        peer_type: str = "all",  # "all" | "channel" | "chat"
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search channels/chats via ``/channels/search``.

        Returns the raw ``items`` list — each item is a channel
        object straight from TGStat. The full TGStat channel
        schema is documented at
        https://api.tgstat.ru/docs/ru/objects/channel.html
        but the fields we care about are:

        * ``tg_id`` (int) — Telegram's internal id.
        * ``username`` (str, without ``@``) — public handle.
        * ``title`` (str)
        * ``about`` (str) — channel description.
        * ``participants_count`` (int)
        * ``peer_type`` (str) — ``"channel"`` or ``"chat"``.
        * ``category`` (str)
        * ``language`` (str)
        * ``country`` (str)
        * ``ci_index`` (float) — TGStat's "involvement index".

        Raises
        ------
        TGStatError
            If the API returns a non-OK response.
        """
        if not self._token:
            raise TGStatError(
                "TGSTAT_API_TOKEN is not configured. Get a token at "
                "https://tgstat.ru/my/profile (plan S or above) and put "
                "it in the backend's .env as TGSTAT_API_TOKEN=..."
            )
        if not q and not category:
            raise TGStatError(
                "TGStat /channels/search requires at least one of: "
                "q (keyword) or category."
            )
        if peer_type not in ("all", "channel", "chat"):
            raise ValueError(f"peer_type must be all|channel|chat, got {peer_type!r}")
        # The API caps limit at 100 per request. We respect the
        # cap and let the caller loop if they need more.
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))

        params: dict[str, Any] = {
            "token": self._token,
            "peer_type": peer_type,
            "limit": limit,
        }
        if q:
            params["q"] = q
        if category:
            params["category"] = category
        if country:
            params["country"] = country
        if language:
            params["language"] = language
        if offset:
            params["offset"] = offset

        client = await self._get_client()
        # ``channels/search`` lives in the Stat API namespace on
        # the same host — pick the Stat endpoint.
        resp = await client.get("/channels/search", params=params)
        if resp.status_code != 200:
            raise TGStatError(
                f"TGStat /channels/search HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        if data.get("status") != "ok":
            raise TGStatError(
                f"TGStat error: {data.get('error') or data!r}"
            )
        response = data.get("response") or {}
        return list(response.get("items") or [])

    async def get_channel(self, channel_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single channel by ``@username`` or numeric id.

        Returns ``None`` if TGStat doesn't have the channel.
        """
        if not self._token:
            raise TGStatError("TGSTAT_API_TOKEN is not configured")
        client = await self._get_client()
        resp = await client.get(
            "/channels/get",
            params={"token": self._token, "channelId": channel_id},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise TGStatError(
                f"TGStat /channels/get HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        if data.get("status") != "ok":
            return None
        return data.get("response")


# Module-level singleton — re-uses the same client across requests.
tgstat_service = TGStatService()
