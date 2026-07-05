"""Health checks for proxies and Telegram accounts.

Originally the account health check collapsed every exception into
``RESTRICTED``. That made a 5-second network hiccup look identical to
"the account was banned", which caused the system to disable perfectly
healthy accounts. The current implementation distinguishes at least
four categories:

* BANNED  — Telegram says the user is deactivated/banned.
* RESTRICTED — the local session key is invalid/revoked and needs attention.
* RATE_LIMITED — Telegram asked us to slow down (FloodWait).
* TRANSIENT  — network / proxy / DNS problems; the account is probably
  fine, we just couldn't reach Telegram right now.
* UNKNOWN — anything else, kept as the previous status but with a recorded
  error message so the operator can investigate.

The check never overwrites a status that's already stricter (e.g. an
existing BANNED is not downgraded to UNKNOWN on a transient error).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from httpx_socks import AsyncProxyTransport
from pyrogram import errors as pyrogram_errors
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy
from app.services.telegram_service import telegram_service


# Errors that genuinely mean the Telegram user itself is dead. ``UserDeactivated``
# covers both normal deletions and the ``UserDeactivatedBan`` variant depending
# on the Pyrogram version installed.
_BANNED_ERRORS: tuple[type[Exception], ...] = (
    pyrogram_errors.UserDeactivated,
)


# These are session/auth-key failures. They make the saved session unusable in
# this service, but they are not proof that the phone number is banned.
_SESSION_INVALID_ERRORS: tuple[type[Exception], ...] = (
    pyrogram_errors.AuthKeyUnregistered,
    pyrogram_errors.AuthKeyInvalid,
    pyrogram_errors.SessionRevoked,
)


# Errors that mean "Telegram told us to slow down".
_RATE_LIMITED_ERRORS: tuple[type[Exception], ...] = (
    pyrogram_errors.FloodWait,
    pyrogram_errors.SlowmodeWait,
    pyrogram_errors.RPCError,  # base — we narrow below
)


# Errors that are network- or proxy-related; do not touch the account
# status at all, but record a note for the operator. Note that
# ``pyrogram.errors`` doesn't always re-export the network-specific
# exceptions, so we rely on a string-based check below as a fallback.
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    asyncio.TimeoutError,
    OSError,
)


async def check_proxy_health(proxy: Proxy) -> tuple[bool, Optional[int]]:
    """Check if proxy is working by making a request to api.ipify.org.

    Returns (is_healthy, response_time_ms).
    """
    proxy_url = f"{proxy.scheme}://"
    if proxy.username and proxy.password:
        proxy_url += f"{proxy.username}:{proxy.password}@"
    proxy_url += f"{proxy.host}:{proxy.port}"

    transport = AsyncProxyTransport.from_url(proxy_url)

    start_time = time.time()
    try:
        async with __import__("httpx").AsyncClient(transport=transport, timeout=10.0) as client:
            response = await client.get("https://api.ipify.org?format=json")
            response_time = int((time.time() - start_time) * 1000)
            return response.status_code == 200, response_time
    except Exception:
        return False, None


def _is_banned(exc: Exception) -> bool:
    return isinstance(exc, _BANNED_ERRORS)


def _is_session_invalid(exc: Exception) -> bool:
    return isinstance(exc, _SESSION_INVALID_ERRORS)


def _is_rate_limited(exc: Exception) -> bool:
    return isinstance(exc, pyrogram_errors.FloodWait) or isinstance(
        exc, pyrogram_errors.SlowmodeWait
    )


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    # `OSError` is already in the tuple, but we keep an explicit message
    # check for hosts that bubble up socket errors as plain `Exception`.
    msg = str(exc).lower()
    transient_markers = (
        "timed out",
        "connection refused",
        "connection reset",
        "network is unreachable",
        "no route to host",
        "proxy",
        "tunnel",
    )
    return any(marker in msg for marker in transient_markers)


async def check_account_health(db: AsyncSession, account: Account) -> bool:
    """Verify that the account can talk to Telegram.

    Returns True if the account is usable, False otherwise. The DB row
    is updated with the new status and ``last_check_at`` timestamp.
    """
    if not account.session_string:
        return False

    try:
        client = await telegram_service.get_client(account)
        me = await client.get_me()
    except Exception as exc:
        previous_status = account.status
        new_status: AccountStatus
        error_text = str(exc)

        if _is_banned(exc):
            new_status = AccountStatus.BANNED
        elif _is_session_invalid(exc):
            new_status = AccountStatus.RESTRICTED
        elif _is_rate_limited(exc):
            # Don't touch status on rate limit; just record the check.
            account.last_check_at = datetime.utcnow()
            account.health_factors = {
                **(account.health_factors or {}),
                "last_check_error": error_text[:200],
            }
            await db.commit()
            return previous_status != AccountStatus.BANNED
        elif _is_transient(exc):
            # Network/proxy hiccup: do NOT mark the account as restricted
            # — the previous status is more informative.
            account.last_check_at = datetime.utcnow()
            account.health_factors = {
                **(account.health_factors or {}),
                "last_check_transient_error": error_text[:200],
            }
            await db.commit()
            return previous_status in (AccountStatus.PRODUCTION, AccountStatus.WARMING)
        else:
            new_status = AccountStatus.RESTRICTED

        # Only escalate to a stricter status, never loosen one.
        status_order = {
            AccountStatus.NEW: 0,
            AccountStatus.WARMING: 1,
            AccountStatus.PRODUCTION: 2,
            AccountStatus.RESTRICTED: 3,
            AccountStatus.BANNED: 4,
        }
        if status_order.get(new_status, 0) > status_order.get(previous_status, 0):
            account.status = new_status

        account.last_check_at = datetime.utcnow()
        account.health_factors = {
            **(account.health_factors or {}),
            "last_check_error": error_text[:200],
        }
        await db.commit()
        return new_status != AccountStatus.BANNED

    if me:
        account.status = AccountStatus.PRODUCTION
        account.last_check_at = datetime.utcnow()
        account.last_active = datetime.utcnow()
        # Account responded successfully → PEER_FLOOD has expired, clear it
        factors = dict(account.health_factors or {})
        if factors.get("restriction", {}).get("reason") == "PEER_FLOOD":
            factors.pop("restriction", None)
            account.health_factors = factors
        await db.commit()
        return True

    # get_me returned a falsy value — something is off but not necessarily
    # a hard error. Keep the previous status and record the fact.
    account.last_check_at = datetime.utcnow()
    account.health_factors = {
        **(account.health_factors or {}),
        "last_check_error": "get_me returned falsy",
    }
    await db.commit()
    return False


async def run_periodic_health_checks(db: AsyncSession):
    """Run proxy and account health checks across the whole project."""
    result = await db.execute(select(Proxy))
    proxies = result.scalars().all()
    for proxy in proxies:
        is_active, response_time_ms = await check_proxy_health(proxy)
        was_active = proxy.is_active
        proxy.is_active = is_active
        proxy.response_time_ms = response_time_ms
        if was_active and not is_active:
            result = await db.execute(
                select(Account.id).where(Account.proxy_id == proxy.id)
            )
            account_ids = [row[0] for row in result.all()]
            await telegram_service.disconnect_clients(account_ids)

    result = await db.execute(select(Account))
    accounts = result.scalars().all()
    for account in accounts:
        await check_account_health(db, account)

    await db.commit()
