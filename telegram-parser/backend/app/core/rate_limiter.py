"""Token-bucket rate limiter for Telegram actions.

Built on top of :mod:`app.core.safety_guidelines` so the actual
numbers come from one source of truth. The limiter is per
(``account_id``, ``action``) — same account doing two different
things still gets separate buckets.

If Redis is unreachable we degrade gracefully: we still sleep for
the phase's minimum delay so the request is rate-shaped, just
without the distributed coordination. Better a slow bot than a
500-erroring API.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.safety_guidelines import (
    ACTION_LIMITS,
    AccountPhase,
    ActionLimit,
    FLOODWAIT_BACKOFF,
    phase_for_age_days,
    limit_for,
    should_skip_action as guideline_should_skip,
)

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when the daily quota for a (account, action) is exhausted."""

    def __init__(self, action: str, account_id: int, limit: float, phase: str):
        super().__init__(
            f"Daily limit exceeded for {action} on account {account_id} "
            f"(phase={phase}): {limit}"
        )
        self.action = action
        self.account_id = account_id
        self.limit = limit
        self.phase = phase


class NewbornAccountError(Exception):
    """Raised when an action is attempted on a ``newborn`` account.

    Day 1-3 accounts should not perform ANY outbound action. The
    service layer should catch this and skip the recipient
    gracefully.
    """

    def __init__(self, account_id: int, phase: str):
        super().__init__(
            f"Account {account_id} is in {phase} phase — outbound "
            f"actions are disabled for the first 3 days"
        )
        self.account_id = account_id
        self.phase = phase


class SkipAction(Exception):
    """Raised when the humanization envelope says "skip this one".

    ``human_like_probability < 1.0`` (comment 0.8, reaction 0.7)
    simulates a user who doesn't act on every opportunity. The
    limiter raises this instead of silently returning so the caller
    ACTUALLY skips the action (and no token is spent). Previously the
    skip returned normally, the caller still performed the action, and
    only the counter was skewed — i.e. the account did MORE than the
    daily cap, the opposite of the intended safety behaviour.
    """

    def __init__(self, action: str, account_id: int):
        super().__init__(
            f"Humanization skip for {action} on account {account_id}"
        )
        self.action = action
        self.account_id = account_id


class RateLimiter:
    """Async wrapper around redis-py that implements a token bucket."""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or settings.REDIS_URL
        self._client = None
        self._disabled = False
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._disabled:
            return None
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            try:
                import redis.asyncio as redis_asyncio  # type: ignore

                self._client = redis_asyncio.from_url(
                    self._redis_url,
                    password=settings.REDIS_PASSWORD or None,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                await asyncio.wait_for(self._client.ping(), timeout=2.0)
                return self._client
            except Exception as exc:
                logger.warning(
                    "RateLimiter could not connect to Redis (%s) — falling back to no-op",
                    exc,
                )
                self._disabled = True
                return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def acquire(
        self,
        action: str,
        account_id: int,
        *,
        account_age_days: int = 30,
        min_delay: float | None = None,
        max_delay: float | None = None,
        limits: Optional[dict[str, float]] = None,
    ) -> None:
        """Reserve one token for ``(action, account_id)``.

        Parameters
        ----------
        action
            ``"send"``/``"comment"``/``"reaction"``/``"join"``/
            ``"search_members"``/``"search_global"``/``"get_dialogs"``.
        account_id
            The Telegram account the action is being performed on.
        account_age_days
            Age in days, used to pick the right
            :class:`AccountPhase`. The caller should pass
            ``(now - account.created_at).days``; we don't query the
            DB here so the limiter stays cheap.
        min_delay
            Optional override for the minimum delay. Used by the
            service layer when ``campaign.min_delay`` should win
            over the safety envelope (e.g. a campaign was
            configured to wait longer than the global minimum).
        max_delay
            Optional upper bound for the jitter. Interactive operations such
            as a manually started search use a short bounded delay while still
            sharing the same counters and FloodWait handling.
        """
        phase = phase_for_age_days(account_age_days)
        eff = limit_for(action, phase)
        eff_min = min_delay if min_delay is not None else eff.min_delay_sec
        eff_max = max_delay if max_delay is not None else eff.max_delay_sec
        eff_max = max(eff_min, eff_max)

        # Phase 0 multiplier → block the action entirely. We raise a
        # different exception so the service layer can mark the
        # recipient SKIPPED with a clear reason.
        if phase.multiplier == 0.0 or eff.per_day <= 0:
            raise NewbornAccountError(account_id, phase.name)

        # 30% "I scrolled past this post" simulation for reactions /
        # comments. We RAISE so the caller actually skips the action
        # (and no token is spent). Returning normally here would let
        # the caller perform the action anyway — the old bug.
        if guideline_should_skip_action(action, eff):
            raise SkipAction(action, account_id)

        client = await self._get_client()
        if client is None:
            # Redis-down fallback. Redis is only the *fast* counter;
            # when it is unavailable we still enforce the per-day cap
            # via a Postgres-backed counter so the daily quota is not
            # silently lost (the counter lives in accounts.health_factors,
            # shared across processes). May raise RateLimitExceeded,
            # which callers already handle. Also sleeps the phase delay.
            await self._db_daily_guard(
                action, account_id, eff.per_day, eff_min, eff_max, phase.name
            )
            return

        # Daily counter. The TTL expires at midnight UTC.
        # All Redis ops are wrapped in a 5s timeout: if the connection
        # is half-open (stale TCP), operations hang indefinitely without
        # it — socket_timeout in redis.asyncio is not always honoured.
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        daily_key = f"rl:{action}:{account_id}:day:{day}"
        try:
            current = await asyncio.wait_for(client.incr(daily_key), timeout=5)
            if current == 1:
                await asyncio.wait_for(
                    client.expire(daily_key, _seconds_until_midnight_utc()), timeout=5
                )
            if current > eff.per_day:
                raise RateLimitExceeded(action, account_id, eff.per_day, phase.name)
        except RateLimitExceeded:
            raise
        except Exception as exc:
            logger.warning("RateLimiter daily counter failed: %s — resetting client", exc)
            self._client = None
            self._disabled = False
            await asyncio.sleep(_jitter(eff_min, eff_max))
            return

        # Per-second / per-minute bucket. ZSET-based leaky bucket.
        try:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            second_key = f"rl:{action}:{account_id}:sec"
            minute_key = f"rl:{action}:{account_id}:min"
            await asyncio.wait_for(client.zremrangebyscore(second_key, 0, now_ms - 1000), timeout=5)
            await asyncio.wait_for(client.zremrangebyscore(minute_key, 0, now_ms - 60_000), timeout=5)
            sec_count = await asyncio.wait_for(client.zcard(second_key), timeout=5)
            min_count = await asyncio.wait_for(client.zcard(minute_key), timeout=5)

            sleep_for = 0.0
            if sec_count >= eff.per_second:
                oldest = await asyncio.wait_for(client.zrange(second_key, 0, 0, withscores=True), timeout=5)
                if oldest:
                    _, score = oldest[0]
                    sleep_for = max(sleep_for, (score + 1000 - now_ms) / 1000.0)
            if min_count >= eff.per_minute:
                oldest = await asyncio.wait_for(client.zrange(minute_key, 0, 0, withscores=True), timeout=5)
                if oldest:
                    _, score = oldest[0]
                    sleep_for = max(sleep_for, (score + 60_000 - now_ms) / 1000.0)

            member = f"{now_ms}:{id(object())}"
            await asyncio.wait_for(client.zadd(second_key, {member: now_ms}), timeout=5)
            await asyncio.wait_for(client.expire(second_key, 2), timeout=5)
            await asyncio.wait_for(client.zadd(minute_key, {member: now_ms}), timeout=5)
            await asyncio.wait_for(client.expire(minute_key, 65), timeout=5)

            await asyncio.sleep(sleep_for or _jitter(eff_min, eff_max))
        except RateLimitExceeded:
            raise
        except Exception as exc:
            logger.warning("RateLimiter bucket op failed: %s — resetting client", exc)
            self._client = None
            self._disabled = False
            await asyncio.sleep(_jitter(eff_min, eff_max))

    async def _db_daily_guard(
        self,
        action: str,
        account_id: int,
        per_day: float,
        eff_min: float,
        eff_max: float,
        phase_name: str,
    ) -> None:
        """Enforce the per-day cap without Redis, using Postgres.

        The counter is stored in ``accounts.health_factors['rl_fallback']``
        as ``{action: {"day": "YYYYMMDD", "count": N}}`` — no schema
        change needed, and because it lives in Postgres it survives the
        subprocess model that drives Celery tasks (an in-memory counter
        would reset on every task and enforce nothing).

        Raises :class:`RateLimitExceeded` when the cap is exceeded.
        Any DB failure degrades to a plain sleep — better slow than 500.
        """
        try:
            from sqlalchemy import select  # noqa: PLC0415
            from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

            from app.db.session import SessionLocal  # noqa: PLC0415
            from app.models.account import Account  # noqa: PLC0415

            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            over_cap = False
            async with SessionLocal() as db:
                acc = (
                    await db.execute(select(Account).where(Account.id == account_id))
                ).scalar_one_or_none()
                if acc is not None:
                    factors = dict(acc.health_factors or {})
                    fallback = dict(factors.get("rl_fallback") or {})
                    bucket = fallback.get(action)
                    if not isinstance(bucket, dict) or bucket.get("day") != day:
                        bucket = {"day": day, "count": 0}
                    bucket["count"] = int(bucket.get("count", 0)) + 1
                    fallback[action] = bucket
                    factors["rl_fallback"] = fallback
                    acc.health_factors = factors
                    flag_modified(acc, "health_factors")
                    await db.commit()
                    over_cap = per_day > 0 and bucket["count"] > per_day
            if over_cap:
                raise RateLimitExceeded(action, account_id, per_day, phase_name)
        except RateLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB daily fallback failed: %s — sleeping only", exc)
        await asyncio.sleep(_jitter(eff_min, eff_max))

    async def daily_count(self, action: str, account_id: int) -> int:
        client = await self._get_client()
        if client is None:
            return 0
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        try:
            value = await client.get(f"rl:{action}:{account_id}:day:{day}")
            return int(value or 0)
        except Exception:
            return 0

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    # ------------------------------------------------------------------
    # Phase-aware helpers used by the warmup runner
    # ------------------------------------------------------------------
    def phase_for(self, account_age_days: int) -> AccountPhase:
        return phase_for_age_days(account_age_days)

    def limit_for(self, action: str, account_age_days: int) -> ActionLimit:
        return limit_for(action, phase_for_age_days(account_age_days))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def guideline_should_skip_action(action: str, eff: ActionLimit) -> bool:
    """Wrap the safety_guidelines helper with the right signature."""
    return guideline_should_skip(
        action=action,
        phase=phase_for_age_days(30),  # phase doesn't matter when multi > 0
        human_like_probability=eff.human_like_probability,
    )


def _jitter(min_delay: float, max_delay: float) -> float:
    if max_delay < min_delay:
        max_delay = min_delay
    return random.uniform(min_delay, max_delay)


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    next_midnight = (now + __import__("datetime").timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(60, int((next_midnight - now).total_seconds()))


# Module-level singleton — the rest of the codebase imports ``rate_limiter``.
rate_limiter = RateLimiter()

# Re-export the constants the rest of the codebase needs.
__all__ = [
    "RateLimiter",
    "RateLimitExceeded",
    "NewbornAccountError",
    "SkipAction",
    "rate_limiter",
    "ACTION_LIMITS",
    "FLOODWAIT_BACKOFF",
]
