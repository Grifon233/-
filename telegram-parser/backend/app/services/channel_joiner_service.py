"""Progressive channel-joining scheduler — distributed mode.

Each account owns a SLICE of the global pool (set by distribute_pool()).
It only joins sources in its own slice, so every source ends up covered
by exactly ONE account.  No duplicate joins across accounts.

Daily quota progression (per account, per calendar day):
    Day 0 → 20
    Day 1 → 30
    Day 2 → 40
    Day 3+ → 50 (cap — safe daily limit)

The daily quota is NOT joined in one continuous run. Instead it is spread
across several "episodes" (bursts) through the day:
  * within an episode: 5-6 joins, 1-3.3 minute pauses between them (so a
    burst finishes well within half an hour);
  * between episodes: roughly every half hour (25-35 minute jitter so it
    isn't a dead-exact metronome), randomized independently per account so
    accounts drift apart instead of firing in lockstep;
  * a full nightly sleep phase — no episodes at all between 00:00 and
    08:00 Yekaterinburg time (see the active-hours gate in
    ``app.main._channel_join_loop``, which is what actually stops ticks
    from happening at night — this module just doesn't run unless called).

Accounts without a proxy are always skipped.
"""
from __future__ import annotations

import logging
import random
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.models.telegram_source import TelegramSource
from app.services.telegram_service import extract_join_target, telegram_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Progression — max 50/day, ramp-up from a 20/day floor
# ---------------------------------------------------------------------------

JOIN_PROGRESSION: List[int] = [20, 30, 40, 50]
DAILY_CAP = 50

# Episode (burst) shape — how a day's quota is chopped up and spread out.
EPISODE_MIN_JOINS = 5
EPISODE_MAX_JOINS = 6
INTRA_EPISODE_PAUSE_MIN_SEC = 60.0
INTRA_EPISODE_PAUSE_MAX_SEC = 200.0
EPISODE_GAP_MIN_MINUTES = 25.0
EPISODE_GAP_MAX_MINUTES = 35.0
# Small stagger applied the first time a new day's quota is picked up, so
# accounts that roll over to a new day at the same tick don't all start
# their first episode of the day at the exact same instant.
NEW_DAY_INITIAL_STAGGER_MAX_MINUTES = 25.0


def _batch_size(session_count: int) -> int:
    idx = min(session_count, len(JOIN_PROGRESSION) - 1)
    return JOIN_PROGRESSION[idx]


def _today_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Pool distribution
# ---------------------------------------------------------------------------

async def distribute_pool(project_id: int, group_id: int | None = None) -> Dict[str, Any]:
    """Split all enabled sources evenly across eligible accounts.

    Sources in the pool are shuffled, then divided into N equal slices
    (one per account).  Each account's join_assigned_source_ids is replaced
    with its new slice.  join_session_count and join_last_session_at are
    reset so each account starts fresh from session 0.

    Args:
        project_id: project to distribute within
        group_id: if set, only sources from this source group are used;
                  otherwise all enabled project sources are used.
    """
    async with SessionLocal() as db:
        # Fetch sources
        q = select(TelegramSource).where(
            TelegramSource.project_id == project_id,
            TelegramSource.is_enabled.is_(True),
        )
        if group_id is not None:
            q = q.where(TelegramSource.group_id == group_id)
        res = await db.execute(q)
        sources = res.scalars().all()
        source_ids = [s.id for s in sources if s.normalized_link]

        # Fetch eligible accounts (have session + proxy, not banned)
        res2 = await db.execute(
            select(Account).where(
                Account.project_id == project_id,
                Account.session_string.isnot(None),
                Account.proxy_id.isnot(None),
                Account.status.notin_([AccountStatus.BANNED.value, AccountStatus.RESTRICTED.value]),
            )
        )
        accounts = res2.scalars().all()

        if not accounts:
            return {"error": "no_eligible_accounts", "accounts": 0, "sources": 0}
        if not source_ids:
            return {"error": "no_sources", "accounts": len(accounts), "sources": 0}

        # Shuffle sources for fair distribution
        random.shuffle(source_ids)
        n = len(accounts)

        # Split into slices — remainder goes to first accounts
        base = len(source_ids) // n
        remainder = len(source_ids) % n
        slices: List[List[int]] = []
        pos = 0
        for i in range(n):
            size = base + (1 if i < remainder else 0)
            slices.append(source_ids[pos:pos + size])
            pos += size

        # Assign slices and reset progress
        assignments = []
        for acc, sl in zip(accounts, slices):
            acc.join_assigned_source_ids = sl
            flag_modified(acc, "join_assigned_source_ids")
            acc.join_session_count = 0
            acc.join_last_session_at = None
            acc.joined_source_ids = []
            flag_modified(acc, "joined_source_ids")
            acc.join_day_date = None
            acc.join_day_target = None
            acc.join_day_joined = 0
            acc.join_next_episode_at = None
            assignments.append({
                "account_id": acc.id,
                "phone": acc.phone_number,
                "assigned": len(sl),
            })

        await db.commit()

    return {
        "accounts": n,
        "total_sources": len(source_ids),
        "assignments": assignments,
    }


# ---------------------------------------------------------------------------
# Core join session
# ---------------------------------------------------------------------------

async def run_join_session(account: Account, db: AsyncSession) -> Dict[str, Any]:
    """Run one join *episode* (burst) for a single account, if one is due.

    A calendar day's quota (``JOIN_PROGRESSION[join_session_count]``) is
    spread across several calls to this function rather than joined in one
    continuous run — see the module docstring for the episode/gap shape.
    Most calls will legitimately no-op (``skip_reason`` set) because the
    account's own randomized ``join_next_episode_at`` hasn't arrived yet or
    today's quota is already met — that's the point: each account has its
    own ragged schedule instead of a shared metronome.
    """
    result: Dict[str, Any] = {
        "account_id": account.id,
        "phone": account.phone_number,
        "joined": 0,
        "skipped": 0,
        "errors": [],
        "session_number": account.join_session_count or 0,
        "total_joined": len(account.joined_source_ids or []),
        "skip_reason": None,
    }

    if not account.proxy_id:
        result["skip_reason"] = "no_proxy"
        return result

    if not account.session_string:
        result["skip_reason"] = "no_session"
        return result

    if account.status in (AccountStatus.BANNED, AccountStatus.RESTRICTED):
        result["skip_reason"] = f"status_{account.status.value if hasattr(account.status, 'value') else account.status}"
        return result

    now = datetime.utcnow()
    today = _today_str()

    # New calendar day → pick this day's quota and stagger its first
    # episode so accounts that roll over at the same tick don't all fire
    # their first join at the exact same instant.
    if account.join_day_date != today:
        account.join_day_date = today
        account.join_day_target = _batch_size(account.join_session_count or 0)
        account.join_day_joined = 0
        account.join_next_episode_at = now + timedelta(
            minutes=random.uniform(0, NEW_DAY_INITIAL_STAGGER_MAX_MINUTES)
        )
        await db.commit()

    if account.join_next_episode_at and now < account.join_next_episode_at:
        result["skip_reason"] = "waiting_for_next_episode"
        return result

    remaining_today = (account.join_day_target or 0) - (account.join_day_joined or 0)
    if remaining_today <= 0:
        result["skip_reason"] = "day_target_reached"
        return result

    # Build candidate list from assigned slice
    assigned: List[int] = account.join_assigned_source_ids or []
    already_joined: List[int] = list(account.joined_source_ids or [])

    remaining_ids = [sid for sid in assigned if sid not in already_joined]
    if not remaining_ids:
        result["skip_reason"] = "slice_exhausted"
        logger.info("channel_joiner: acc %s slice exhausted (%d/%d done)",
                    account.id, len(already_joined), len(assigned))
        return result

    # Fetch source objects for remaining ids
    res = await db.execute(
        select(TelegramSource).where(
            TelegramSource.id.in_(remaining_ids),
            TelegramSource.is_enabled.is_(True),
        )
    )
    candidates = [s for s in res.scalars().all() if s.normalized_link]
    if not candidates:
        result["skip_reason"] = "no_valid_sources"
        return result

    # Preserve slice order (don't random-shuffle — accounts run in order)
    id_order = {sid: i for i, sid in enumerate(remaining_ids)}
    candidates.sort(key=lambda s: id_order.get(s.id, 9999))

    episode_n = min(
        random.randint(EPISODE_MIN_JOINS, EPISODE_MAX_JOINS),
        remaining_today,
        len(candidates),
    )
    to_join = candidates[:episode_n]

    logger.info(
        "channel_joiner: acc %s day-tier #%d episode — joining %d (today %d/%d so far), remaining in slice %d",
        account.id, account.join_session_count, len(to_join),
        account.join_day_joined, account.join_day_target, len(remaining_ids),
    )

    # Connect
    try:
        client = await asyncio.wait_for(telegram_service.get_client(account), timeout=30)
    except Exception as exc:
        result["skip_reason"] = f"connect_error"
        logger.warning("channel_joiner: acc %s connect failed: %s", account.id, exc)
        return result

    # Join loop — short pauses inside a burst so it stays well under 30 min.
    for source in to_join:
        try:
            await client.join_chat(extract_join_target(source.normalized_link))
            already_joined.append(source.id)
            result["joined"] += 1
            logger.info("channel_joiner: acc %s joined %s", account.id, source.normalized_link)
        except Exception as exc:
            result["errors"].append({
                "source_id": source.id,
                "link": source.normalized_link,
                "error": str(exc)[:100],
            })
            result["skipped"] += 1
            logger.warning("channel_joiner: acc %s join %s: %s", account.id, source.normalized_link, exc)

        pause = random.uniform(INTRA_EPISODE_PAUSE_MIN_SEC, INTRA_EPISODE_PAUSE_MAX_SEC)
        await asyncio.sleep(pause)

    # Persist — advance today's counter and roll the dice on the next
    # sleep interval before this account is eligible for another episode.
    account.joined_source_ids = already_joined
    flag_modified(account, "joined_source_ids")
    account.join_day_joined = (account.join_day_joined or 0) + len(to_join)
    account.join_last_session_at = datetime.utcnow()
    account.join_next_episode_at = datetime.utcnow() + timedelta(
        minutes=random.uniform(EPISODE_GAP_MIN_MINUTES, EPISODE_GAP_MAX_MINUTES)
    )
    if account.join_day_joined >= (account.join_day_target or 0):
        # Today's quota is met — tomorrow moves to the next progression tier.
        account.join_session_count = (account.join_session_count or 0) + 1
    result["total_joined"] = len(already_joined)

    await db.commit()
    logger.info(
        "channel_joiner: acc %s episode done — joined %d, today %d/%d, total %d/%d",
        account.id, result["joined"], account.join_day_joined, account.join_day_target,
        result["total_joined"], len(assigned),
    )
    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

async def run_all_join_sessions(project_id: int | None = None) -> List[Dict[str, Any]]:
    """Try one join episode for every eligible account.

    When ``project_id`` is ``None`` (the background scheduler's mode) every
    project's eligible accounts are covered in one pass — previously the loop
    hard-coded project 1, so any other project's pool never advanced. A
    concrete ``project_id`` still scopes the run (manual API trigger).

    Most accounts will no-op (see ``run_join_session``'s ``skip_reason``) —
    that's expected, each has its own randomized episode schedule. The
    processing order is shuffled every tick so a fixed DB order doesn't
    turn into a de-facto fixed schedule of its own.
    """
    results: List[Dict[str, Any]] = []

    async with SessionLocal() as db_ids:
        conditions = [
            Account.session_string.isnot(None),
            Account.proxy_id.isnot(None),
            Account.status.notin_([AccountStatus.BANNED.value, AccountStatus.RESTRICTED.value]),
        ]
        if project_id is not None:
            conditions.append(Account.project_id == project_id)
        res = await db_ids.execute(select(Account.id).where(*conditions))
        account_ids = list(res.scalars().all())

    random.shuffle(account_ids)

    for acc_id in account_ids:
        async with SessionLocal() as db:
            res2 = await db.execute(
                select(Account).where(Account.id == acc_id).options(selectinload(Account.proxy))
            )
            account = res2.scalars().first()
            if not account:
                continue
            result = await run_join_session(account, db)
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Coverage / orphan detection
# ---------------------------------------------------------------------------

async def get_pool_coverage(project_id: int) -> Dict[str, Any]:
    """Return per-source coverage + orphan detection.

    Only sources that are assigned to at least one account via
    join_assigned_source_ids appear in the report.
    """
    async with SessionLocal() as db:
        res = await db.execute(
            select(TelegramSource).where(
                TelegramSource.project_id == project_id,
                TelegramSource.is_enabled.is_(True),
            )
        )
        sources = res.scalars().all()
        source_map = {s.id: s for s in sources}

        res2 = await db.execute(
            select(Account).where(Account.project_id == project_id)
        )
        accounts = res2.scalars().all()

    # Build assigned-to index and joined index
    assigned_to: Dict[int, Dict] = {}  # source_id → account info
    joined_by: Dict[int, Dict] = {}    # source_id → account info

    accounts_summary = []
    for acc in accounts:
        if not (acc.session_string and acc.proxy_id):
            continue
        assigned = acc.join_assigned_source_ids or []
        joined = acc.joined_source_ids or []
        acc_info = {
            "account_id": acc.id,
            "phone": acc.phone_number,
            "status": acc.status.value if hasattr(acc.status, "value") else acc.status,
            "join_session_count": acc.join_session_count or 0,
        }
        for sid in assigned:
            assigned_to[sid] = acc_info
        for sid in joined:
            joined_by[sid] = acc_info

        total_assigned = len(assigned)
        total_joined = len(joined)
        remaining = total_assigned - total_joined
        sessions_to_finish = 0
        if remaining > 0:
            count = total_joined
            sess = acc.join_session_count or 0
            while count < total_assigned:
                count += _batch_size(sess)
                sess += 1
                sessions_to_finish += 1

        accounts_summary.append({
            "account_id": acc.id,
            "phone": acc.phone_number,
            "status": acc.status.value if hasattr(acc.status, "value") else acc.status,
            "assigned_count": total_assigned,
            "joined_count": total_joined,
            "remaining": max(0, remaining),
            "join_session_count": acc.join_session_count or 0,
            "join_last_session_at": acc.join_last_session_at.isoformat() if acc.join_last_session_at else None,
            "next_batch_size": _batch_size(acc.join_session_count or 0),
            "sessions_to_finish": sessions_to_finish,
            "join_day_target": acc.join_day_target,
            "join_day_joined": acc.join_day_joined or 0,
            "join_next_episode_at": acc.join_next_episode_at.isoformat() if acc.join_next_episode_at else None,
        })

    # Build source list from assigned set
    all_assigned_ids = set(assigned_to.keys())
    source_list = []
    orphaned_count = 0
    not_yet_joined = 0

    for sid, s in source_map.items():
        if sid not in all_assigned_ids:
            continue  # not in any slice — skip (unassigned)
        owner = assigned_to.get(sid)
        joined = joined_by.get(sid)
        is_orphaned = owner is None
        is_joined = joined is not None
        if is_orphaned:
            orphaned_count += 1
        if not is_joined:
            not_yet_joined += 1
        source_list.append({
            "id": sid,
            "title": s.title or s.normalized_link,
            "link": s.normalized_link,
            "type": s.source_type.value if hasattr(s.source_type, "value") else s.source_type,
            "assigned_to": owner,
            "joined_by": joined,
            "is_orphaned": is_orphaned,
            "is_joined": is_joined,
        })

    source_list.sort(key=lambda x: (not x["is_orphaned"], x["is_joined"], x["id"]))

    total = len(source_list)
    joined_count = total - not_yet_joined
    return {
        "total_sources": len(sources),
        "assigned_sources": total,
        "joined": joined_count,
        "not_yet_joined": not_yet_joined,
        "orphaned": orphaned_count,
        "coverage_percent": round(joined_count / total * 100) if total else 0,
        "sources": source_list,
        "accounts_summary": accounts_summary,
    }
