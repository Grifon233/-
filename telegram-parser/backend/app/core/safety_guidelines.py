"""Safety guidelines for Telegram-account automation.

All numbers and recommendations in this file are derived from a
combination of:

* Official Telegram Bot FAQ (core.telegram.org/bots/faq) — the only
  hard limits Telegram publishes.
* grammY's "Scaling Up IV: Flood Limits" guide
  (https://grammy.dev/advanced/flood) — the cleanest public write-up
  of what to do when you hit 429.
* TDLib community reports (https://github.com/tdlib/td/issues/3034).
* Industry warm-up guides (TelePilot Pro, IPFoxy 7-day SOP,
  partnershare.cn, spredo.io, crmchat.ai).
* Direct experimentation reports on r/Telegram, r/TelegramBots, and
  GitHub issues for Pyrogram, Telethon, Hikka, PagerMaid-Pyro.

The data points that the rest of the codebase cares about live in
three structures:

* ``ACCOUNT_PHASES`` — graduated limits by account age. New
  accounts get a fraction of an aged account's quota, exactly the
  way real warm-up SOPs recommend.
* ``ACTION_LIMITS`` — per-(action, phase) hard caps for
  ``send``/``comment``/``reaction``/``join``/``search_global``/etc.
* ``WARMUP_SCHEDULE`` — day-by-day warm-up plan, used by
  ``app/tasks/warmup.py`` to decide what the account is allowed to
  do today.

Every value is conservative — well below what a power user would
hit, with safety margin. If you raise a number, you accept the
risk of FloodWaits and account bans; the corresponding audit
ticket will have to explain why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# 1. Account age phases
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AccountPhase:
    """A graduated cap on what a Telegram account may do.

    The ``multiplier`` shrinks every per-action limit when the
    account is younger. ``min_delay`` and ``max_delay`` set the
    human-like sleep envelope between actions; the rate limiter
    picks a random value inside the envelope.
    """

    name: str
    min_age_days: int
    max_age_days: int  # exclusive; ``float("inf")`` for the open-ended "aged" phase
    multiplier: float  # applied to ACTION_LIMITS for this account
    min_delay: float  # seconds, hard floor
    max_delay: float  # seconds, hard ceiling
    daily_cap_ratio: float = 1.0  # extra cap for the daily budget
    notes: str = ""


ACCOUNT_PHASES: list[AccountPhase] = [
    AccountPhase(
        name="newborn",
        min_age_days=0,
        max_age_days=3,
        multiplier=0.0,  # disabled
        min_delay=0.0,
        max_delay=0.0,
        daily_cap_ratio=0.0,
        notes=(
            "Days 1-3: profile setup only. No DMs, no joins, no "
            "reactions, no comments. See WARMUP_SCHEDULE day 1-3."
        ),
    ),
    AccountPhase(
        name="infant",
        min_age_days=3,
        max_age_days=7,
        multiplier=0.05,  # 5% of full quota
        min_delay=60.0,  # 1-3 minutes between any Telegram action
        max_delay=180.0,
        daily_cap_ratio=0.10,
        notes=(
            "Days 4-7: light activity. 2-5 DMs/day to known contacts "
            "only, max 1 group join/day, no comments. "
            "Conservative Phase 2 from the 7-day IPFoxy SOP."
        ),
    ),
    AccountPhase(
        name="warming",
        min_age_days=7,
        max_age_days=14,
        multiplier=0.20,  # 20%
        min_delay=30.0,
        max_delay=90.0,
        daily_cap_ratio=0.30,
        notes=(
            "Days 8-14: 10-20 messages/day. Up to 3 group joins/day. "
            "First light reactions on channels in your allowlist. "
            "Mirrors the 'MODERATE MESSAGING' phase in "
            "docs/PROJECT_SUMMARY.md."
        ),
    ),
    AccountPhase(
        name="production",
        min_age_days=14,
        max_age_days=30,
        multiplier=0.50,  # 50%
        min_delay=15.0,
        max_delay=60.0,
        daily_cap_ratio=0.60,
        notes=(
            "Days 15-30: 'FULL PRODUCTION' phase. 30-50 DMs/day, "
            "5-10 group joins/day, reactions enabled. Still under "
            "full quota — observed in practice to keep the trust "
            "score climbing."
        ),
    ),
    AccountPhase(
        name="aged",
        min_age_days=30,
        max_age_days=10**9,
        multiplier=1.0,  # full quota
        min_delay=5.0,
        max_delay=20.0,
        daily_cap_ratio=1.0,
        notes=(
            "30+ days, established trust score. Full quota. Even "
            "so, never exceed 30 messages/second globally per "
            "Telegram's own guidance."
        ),
    ),
]


def effective_account_age_days(account) -> int:
    """Age (in days) to use for rate-limiting an account.

    IMPORTANT: ``account.created_at`` is when the row was inserted into
    OUR database — NOT when the Telegram account was registered. Operators
    import long-lived aged accounts, whose ``created_at`` is "today". Using
    the raw value would mis-classify every imported account as ``newborn``
    and block ALL outbound actions (the bug found when parsing/sending kept
    failing with "newborn phase").

    We use the account STATUS as a proxy for real maturity:
    * ``production`` → treated as aged (>= 30 days);
    * otherwise     → ``max(days-since-import, warmup_level)``.
    """
    from datetime import datetime as _dt

    created_at = getattr(account, "created_at", None)
    created_days = (_dt.utcnow() - (created_at or _dt.utcnow())).days
    status = getattr(account, "status", None)
    status_value = status.value if hasattr(status, "value") else status
    if status_value == "production":
        return max(created_days, 30)
    return max(created_days, getattr(account, "warmup_level", 0) or 0)


def phase_for_age_days(age_days: int) -> AccountPhase:
    """Return the most permissive phase whose window contains the age.

    >>> phase_for_age_days(2).name
    'newborn'
    >>> phase_for_age_days(5).name
    'infant'
    >>> phase_for_age_days(120).name
    'aged'
    """
    for phase in ACCOUNT_PHASES:
        if phase.min_age_days <= age_days < phase.max_age_days:
            return phase
    # Past the last phase → ``aged``.
    return ACCOUNT_PHASES[-1]


# ---------------------------------------------------------------------------
# 2. Per-action hard limits
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ActionLimit:
    """Hard caps for one action, in the "aged" phase.

    Multiplied by ``AccountPhase.multiplier`` for younger accounts.
    """

    name: str
    per_second: float  # reserved for future token-bucket work
    per_minute: float
    per_hour: float
    per_day: float
    min_delay_sec: float
    max_delay_sec: float
    human_like_probability: float = 1.0  # 1.0 = always; 0.7 = 30% skip
    notes: str = ""


# Conservative numbers from public sources, never above what a power
# user would actually do. ``per_second`` is mostly used as a guard
# for token-bucket accounting; Telegram's real hard limit is
# 1/chat/second for the same chat, 30 globally for bulk — the rate
# limiter uses min_delay to honour the 1/chat/second rule.
ACTION_LIMITS: Dict[str, ActionLimit] = {
    # Sending a private message (DM). Hard 1/chat/second; globally
    # 30/second for broadcast. We use a tighter 20/day default for
    # new accounts and ramp to 50/day when the user opts in.
    "send": ActionLimit(
        name="send",
        per_second=1.0,
        per_minute=20.0,
        per_hour=200.0,
        per_day=50.0,  # per-account daily cap
        min_delay_sec=10.0,
        max_delay_sec=40.0,
        human_like_probability=1.0,
        notes=(
            "Telegram hard limit: 1 msg/sec per chat, 30 msg/sec "
            "global broadcast. We use 10-40s jitter + the per-day "
            "cap so a single 24h burst never exceeds what a "
            "moderately active human does. Cold-DM best practice "
            "(crmchat.ai) is 5 DMs/day per new account, +2-3/week."
        ),
    ),
    # Commenting on a channel post (via the linked discussion group).
    "comment": ActionLimit(
        name="comment",
        per_second=0.5,
        per_minute=5.0,
        per_hour=30.0,
        per_day=20.0,
        min_delay_sec=60.0,
        max_delay_sec=180.0,
        human_like_probability=0.8,  # ~20% chance to skip a post
        notes=(
            "Telegram flags mass-commenting as spam. The "
            "human_like_probability=0.8 simulates a user who "
            "skims a channel and reacts to only some posts. "
            "Slow mode in many groups is 30-60s anyway, so the "
            "60-180s delay matches SlowMode constraints."
        ),
    ),
    # Sending a reaction (emoji on a message).
    "reaction": ActionLimit(
        name="reaction",
        per_second=1.0,
        per_minute=10.0,
        per_hour=60.0,
        per_day=200.0,
        min_delay_sec=15.0,
        max_delay_sec=60.0,
        human_like_probability=0.7,
        notes=(
            "Reactions are cheap but rate-bounded per (peer, "
            "message). 60/hr, 200/day is comfortably under the "
            "tier-1 risk threshold observed on spam-flagged userbots. "
            "70% probability ≈ 'I scrolled past 30% of posts'."
        ),
    ),
    # Joining groups/channels.
    "join": ActionLimit(
        name="join",
        per_second=0.2,
        per_minute=2.0,
        per_hour=5.0,
        per_day=10.0,
        min_delay_sec=120.0,
        max_delay_sec=600.0,
        human_like_probability=1.0,
        notes=(
            "Telegram returns 'Too Many Attempts' / FloodWait "
            "after 5-10 fast joins. 2-10 min jitter + max 10/day "
            "keeps the trust score healthy. Newborn phase blocks "
            "joins entirely (0% multiplier)."
        ),
    ),
    # Resolving chat members (``get_chat_members``). This is one of
    # the most expensive Pyrogram calls and is the #1 cause of
    # spam-flagged parsing bots.
    "search_members": ActionLimit(
        name="search_members",
        per_second=0.3,
        per_minute=5.0,
        per_hour=20.0,
        per_day=80.0,
        min_delay_sec=10.0,
        max_delay_sec=30.0,
        human_like_probability=1.0,
        notes=(
            "``client.get_chat_members`` is a heavy operation; "
            "spam-flagged parsers almost always overdo it. 80/day "
            "is plenty for a 10k-member group when you scroll in "
            "pages of 200."
        ),
    ),
    # Global search (``search_global``).
    "search_global": ActionLimit(
        name="search_global",
        per_second=0.2,
        per_minute=3.0,
        per_hour=10.0,
        per_day=30.0,
        min_delay_sec=15.0,
        max_delay_sec=45.0,
        human_like_probability=1.0,
        notes=(
            "``search_global`` triggers FloodWait for many userbots. "
            "Per-keyword per-account limit; 30/day lets a parser "
            "hit 3 different keywords for 10 days."
        ),
    ),
    # Resolving dialogs (``get_dialogs``). Cached on Telegram's side
    # for ~1h, so the limit is mostly a "don't hammer it" guard.
    "get_dialogs": ActionLimit(
        name="get_dialogs",
        per_second=0.1,
        per_minute=1.0,
        per_hour=4.0,
        per_day=8.0,
        min_delay_sec=60.0,
        max_delay_sec=300.0,
        human_like_probability=1.0,
        notes=(
            "``get_dialogs`` is heavy on the first call. The "
            "Telegram client normally does it once on startup; the "
            "rate limiter makes sure we don't poll it on every "
            "campaign tick."
        ),
    ),
}


def limit_for(action: str, phase: AccountPhase) -> ActionLimit:
    """Return the effective ``ActionLimit`` for ``action`` in ``phase``.

    The per-day/per-hour caps are scaled by the phase's
    ``multiplier``; per-second and per-minute use the phase's
    ``multiplier`` too (so a 50% phase has 50% of the per-minute
    budget). Min/max delay are replaced by the phase's
    humanization envelope so a 5% phase actually sleeps 1-3
    minutes per call.
    """
    base = ACTION_LIMITS.get(action)
    if base is None:
        # Default to the ``send`` cap so a typo doesn't open a hole.
        base = ACTION_LIMITS["send"]
    scaled = ActionLimit(
        name=base.name,
        per_second=base.per_second * phase.multiplier,
        per_minute=base.per_minute * phase.multiplier,
        per_hour=base.per_hour * phase.multiplier,
        per_day=base.per_day * phase.daily_cap_ratio,
        min_delay_sec=max(phase.min_delay, base.min_delay_sec),
        max_delay_sec=max(phase.max_delay, base.max_delay_sec),
        human_like_probability=base.human_like_probability,
        notes=base.notes,
    )
    return scaled


# ---------------------------------------------------------------------------
# 3. Warm-up schedule
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WarmupDay:
    day: int  # 1-indexed
    phase: str
    actions: Dict[str, int]  # action -> max count for the day
    notes: str


# Built from the consensus of the 7-day IPFoxy SOP, the 14-day
# TelePilot Pro guide, and the "30-50 DMs/day by day 30" guideline
# in docs/PROJECT_SUMMARY.md. Treat this as the *default*; the
# operator can override per-account via the warmup_level field.
WARMUP_SCHEDULE: Dict[int, WarmupDay] = {
    1: WarmupDay(
        day=1,
        phase="setup",
        actions={"read": 30, "join": 0, "send": 0, "comment": 0, "reaction": 0},
        notes="Profile setup only. Reading only. NO joins, no DMs, no reactions.",
    ),
    2: WarmupDay(
        day=2,
        phase="setup",
        actions={"read": 50, "join": 0, "send": 0, "comment": 0, "reaction": 0},
        notes="Reading only. Still no joins.",
    ),
    3: WarmupDay(
        day=3,
        phase="setup",
        actions={"read": 80, "join": 0, "send": 0, "comment": 0, "reaction": 0},
        notes="Reading only. No joins until day 5.",
    ),
    4: WarmupDay(
        day=4,
        phase="light_messaging",
        actions={"read": 100, "join": 0, "send": 0, "comment": 0, "reaction": 0},
        notes="Day 4: still reading only. Prepare to join on day 5.",
    ),
    5: WarmupDay(
        day=5,
        phase="light_messaging",
        actions={"read": 120, "join": 1, "send": 0, "comment": 0, "reaction": 0},
        notes="Day 5: first join allowed (1 only). No DMs yet.",
    ),
    6: WarmupDay(
        day=6,
        phase="light_messaging",
        actions={"read": 150, "join": 1, "send": 1, "comment": 0, "reaction": 0},
        notes="Day 6: 1 DM to known contact. 1 join max.",
    ),
    7: WarmupDay(
        day=7,
        phase="light_messaging",
        actions={"read": 150, "join": 1, "send": 2, "comment": 0, "reaction": 3},
        notes="End of week 1. Max 1 join/day, 2 DMs, light reactions.",
    ),
    8: WarmupDay(
        day=8,
        phase="moderate",
        actions={"read": 200, "join": 2, "send": 5, "comment": 0, "reaction": 8},
        notes="Days 8-14: up to 5 DMs/day, 2 joins max. No comments yet.",
    ),
    10: WarmupDay(
        day=10,
        phase="moderate",
        actions={"read": 250, "join": 2, "send": 8, "comment": 2, "reaction": 12},
        notes="Day 10: first light comments allowed (2 max). Scale slowly.",
    ),
    12: WarmupDay(
        day=12,
        phase="moderate",
        actions={"read": 300, "join": 4, "send": 15, "comment": 8, "reaction": 25},
        notes="Approaching the production envelope.",
    ),
    14: WarmupDay(
        day=14,
        phase="moderate",
        actions={"read": 400, "join": 4, "send": 20, "comment": 10, "reaction": 30},
        notes="Day 14: 'FULL PRODUCTION' threshold reached. Switch to ``production`` phase.",
    ),
    21: WarmupDay(
        day=21,
        phase="production",
        actions={"read": 500, "join": 5, "send": 30, "comment": 15, "reaction": 40},
        notes="Day 21: full 25-30 DMs/hour capacity (TelePilot Pro).",
    ),
    30: WarmupDay(
        day=30,
        phase="aged",
        actions={"read": 600, "join": 5, "send": 40, "comment": 20, "reaction": 50},
        notes="Aged. Full quota. Stay under 30 msg/sec global even now.",
    ),
}


def warmup_day_for(age_days: int) -> WarmupDay:
    """Return the most recent warm-up day whose number ≤ ``age_days``.

    Days not in the schedule fall back to the previous defined day.
    """
    if not WARMUP_SCHEDULE:
        raise RuntimeError("WARMUP_SCHEDULE is empty")
    first_defined = min(WARMUP_SCHEDULE)
    last_defined = max(WARMUP_SCHEDULE)
    if age_days <= first_defined:
        return WARMUP_SCHEDULE[first_defined]
    chosen_day = min(d for d in WARMUP_SCHEDULE if d >= age_days)
    if chosen_day == age_days:
        return WARMUP_SCHEDULE[chosen_day]
    # ``age_days`` is between two defined days — return the smaller.
    previous = max(d for d in WARMUP_SCHEDULE if d <= age_days)
    return WARMUP_SCHEDULE[previous]


# ---------------------------------------------------------------------------
# 4. FloodWait handling rules
# ---------------------------------------------------------------------------
FLOODWAIT_BACKOFF: dict[str, float] = {
    # A small FloodWait is "slow down for a moment"; honour it
    # exactly and retry once. A large one is "you look spammy";
    # if the value is above ``panic_threshold`` we mark the account
    # as rate-limited and refuse further sends until the cooldown
    # expires.
    "panic_threshold_sec": 600.0,  # 10 min
    "session_pause_sec": 3600.0,  # mark account rate-limited for 1h
    "max_retries_per_call": 3,  # safety net for transient FloodWait
    "backoff_multiplier": 1.5,  # 1.5x on each retry
}


# ---------------------------------------------------------------------------
# 5. Misc safety nets
# ---------------------------------------------------------------------------
BANNED_STATUS_RESET_HOURS = 24  # don't auto-retry banned accounts for 24h
DAILY_UNIQUE_RECIPIENT_SOFT_CAP = 200  # never DM more than 200 unique users/day
RESERVED_KEYWORDS_FOR_BAN_RECOVERY: tuple[str, ...] = (
    "ok",
    "thanks",
    "👍",
    "hello",
)


def flood_cooldown_seconds(flood_wait_seconds: float) -> float:
    """How long to bench an account after a FloodWait, or 0 if none.

    A small FloodWait ("slow down for a moment") is honoured by sleeping and
    retrying. A FloodWait at/above ``panic_threshold_sec`` means Telegram now
    treats the account as spammy — pull it from the pool for
    ``session_pause_sec`` instead of continuing to hammer it. This is the
    protection that ``FLOODWAIT_BACKOFF`` documented but nothing enforced.
    """
    try:
        if float(flood_wait_seconds) >= FLOODWAIT_BACKOFF["panic_threshold_sec"]:
            return FLOODWAIT_BACKOFF["session_pause_sec"]
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def set_flood_cooldown(account, flood_wait_seconds: float) -> bool:
    """Record a FloodWait cooldown on ``account.health_factors`` if warranted.

    Returns True if a cooldown was set. Stores an ISO timestamp under
    ``health_factors['flood_cooldown_until']`` — no schema change needed. The
    caller must persist the account (and flag ``health_factors`` modified for
    plain-JSON columns).
    """
    from datetime import datetime as _dt, timedelta as _td

    secs = flood_cooldown_seconds(flood_wait_seconds)
    if secs <= 0:
        return False
    factors = dict(getattr(account, "health_factors", None) or {})
    factors["flood_cooldown_until"] = (_dt.utcnow() + _td(seconds=secs)).isoformat()
    account.health_factors = factors
    return True


def account_in_flood_cooldown(account) -> bool:
    """True if the account is still inside a FloodWait panic cooldown."""
    from datetime import datetime as _dt

    factors = getattr(account, "health_factors", None) or {}
    until = factors.get("flood_cooldown_until")
    if not until:
        return False
    try:
        return _dt.fromisoformat(until) > _dt.utcnow()
    except (TypeError, ValueError):
        return False


def should_skip_action(
    action: str,
    phase: AccountPhase,
    human_like_probability: float = 1.0,
    *,
    rng=None,
) -> bool:
    """Return True if the action should be skipped this tick.

    ``human_like_probability < 1.0`` simulates a user who doesn't
    act on every opportunity. We use a module-level ``random`` if
    no RNG is passed so the call is deterministic per seed in
    tests.
    """
    if phase.multiplier == 0.0:
        return True
    if human_like_probability >= 1.0:
        return False
    import random as _random

    rng = rng or _random
    return rng.random() > human_like_probability
