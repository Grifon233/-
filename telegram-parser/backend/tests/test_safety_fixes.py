"""Regression tests for the 2026-07-04 safety-algorithm fixes.

These pin the protective behaviours that were previously declared but not
enforced (see SESSIONS/2026-07-04_telegram-parser/REPORT.md):

* the humanization "skip" must actually skip the action (raise SkipAction),
  not silently return and let the caller send anyway (API-003);
* a large FloodWait must bench the account via a cooldown (API-002).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.core.rate_limiter import RateLimiter, SkipAction, NewbornAccountError
from app.core.safety_guidelines import (
    ACTION_LIMITS,
    FLOODWAIT_BACKOFF,
    account_in_flood_cooldown,
    flood_cooldown_seconds,
    set_flood_cooldown,
    phase_for_age_days,
)
from app.models.account import Account, AccountStatus


def _make_account(**overrides) -> Account:
    defaults = dict(
        id=1,
        project_id=1,
        phone_number="+79001234567",
        api_id=12345,
        api_hash="a" * 32,
        session_string=None,
        status=AccountStatus.PRODUCTION,
        proxy_id=42,
        health_factors=None,
    )
    defaults.update(overrides)
    return Account(**defaults)


# --------------------------------------------------------------------------
# API-003 — humanization skip must RAISE, never silently return
# --------------------------------------------------------------------------
def test_skip_action_raised_when_probability_forces_skip():
    """With human_like_probability effectively 0 the limiter must raise
    SkipAction (aged account so it is not blocked as newborn, Redis off so
    we exercise the pure decision path)."""
    limiter = RateLimiter()
    limiter._disabled = True  # force the no-Redis path deterministically

    # Monkeypatch the guideline check to always skip, isolating the contract:
    # a skip decision => SkipAction, not a normal return.
    import app.core.rate_limiter as rl

    original = rl.guideline_should_skip_action
    rl.guideline_should_skip_action = lambda action, eff: True
    try:
        raised = False
        try:
            asyncio.run(
                limiter.acquire("comment", account_id=1, account_age_days=365)
            )
        except SkipAction:
            raised = True
        assert raised, "acquire() must raise SkipAction on a humanization skip"
    finally:
        rl.guideline_should_skip_action = original


def test_no_skip_when_probability_is_full():
    """send has human_like_probability=1.0 → never skips (no SkipAction)."""
    assert ACTION_LIMITS["send"].human_like_probability == 1.0
    limiter = RateLimiter()
    limiter._disabled = True
    # Aged account, send action: should complete without raising SkipAction.
    try:
        asyncio.run(limiter.acquire("send", account_id=1, account_age_days=365))
    except SkipAction:  # pragma: no cover - must not happen
        raise AssertionError("send must never raise SkipAction")
    except NewbornAccountError:  # pragma: no cover
        raise AssertionError("aged account must not be newborn-blocked")


# --------------------------------------------------------------------------
# API-002 — large FloodWait must bench the account
# --------------------------------------------------------------------------
def test_small_floodwait_does_not_cooldown():
    small = FLOODWAIT_BACKOFF["panic_threshold_sec"] - 1
    assert flood_cooldown_seconds(small) == 0.0
    acc = _make_account()
    assert set_flood_cooldown(acc, small) is False
    assert account_in_flood_cooldown(acc) is False


def test_large_floodwait_sets_and_reads_cooldown():
    big = FLOODWAIT_BACKOFF["panic_threshold_sec"] + 1
    assert flood_cooldown_seconds(big) == FLOODWAIT_BACKOFF["session_pause_sec"]
    acc = _make_account()
    assert set_flood_cooldown(acc, big) is True
    assert account_in_flood_cooldown(acc) is True
    # The stored timestamp is in the future, roughly session_pause_sec ahead.
    until = datetime.fromisoformat(acc.health_factors["flood_cooldown_until"])
    assert until > datetime.utcnow()
    assert until <= datetime.utcnow() + timedelta(
        seconds=FLOODWAIT_BACKOFF["session_pause_sec"] + 5
    )


def test_expired_cooldown_reads_as_free():
    acc = _make_account(
        health_factors={
            "flood_cooldown_until": (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        }
    )
    assert account_in_flood_cooldown(acc) is False


def test_newborn_still_blocked_before_skip_logic():
    """Newborn accounts must raise NewbornAccountError (age gate wins)."""
    assert phase_for_age_days(1).name == "newborn"
    limiter = RateLimiter()
    limiter._disabled = True
    try:
        asyncio.run(limiter.acquire("comment", account_id=1, account_age_days=1))
    except NewbornAccountError:
        pass
    else:  # pragma: no cover
        raise AssertionError("newborn account must be blocked")
