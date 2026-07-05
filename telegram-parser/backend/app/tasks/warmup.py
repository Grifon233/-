"""
Account Warmup Service
Автоматический прогрев Telegram аккаунтов.

Backed by :mod:`app.core.safety_guidelines` and
:mod:`app.core.rate_limiter` so every number in here comes from
the same source of truth as the campaign / reactions / groups /
parsers. Newborn accounts (0-3 days) get a multiplier of 0, so
the limiter raises :class:`NewbornAccountError` and we skip the
recipient — no FloodWait on accounts that aren't ready.

Warm-up schedule (mirrors ``WARMUP_SCHEDULE`` in safety_guidelines):

* Day 1-3   — reading only, no DMs, no joins. Profile setup.
* Day 4-7   — 2-5 DMs/day to known contacts, light reactions.
* Day 8-14  — 10-20 DMs/day, more reactions, first joins.
* Day 15-30 — 30-50 DMs/day, 5-10 joins/day, comments enabled.
* Day 30+   — full quota, still under Telegram's 30/sec global.

The previous version had its own hard-coded ``WARMUP_CONFIG`` and
``DELAY_CONFIG`` dicts. Those numbers were conservative but didn't
match the campaign / reactions / groups limiters, so an account
could be 5/5 daily in the warm-up task and still hit FloodWait
when the campaign tried to send 6 DMs in the same hour. The
fix: a single ``safety_guidelines`` table that all the services
read from.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pyrogram.errors import FloodWait, RPCError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.rate_limiter import (
    NewbornAccountError,
    RateLimitExceeded,
    SkipAction,
    rate_limiter,
)
from app.core.safety_guidelines import (
    WARMUP_SCHEDULE,
    phase_for_age_days,
    warmup_day_for,
)
from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.models.telegram_source import TelegramSource
from app.services.safety_manager import get_safety_manager
from app.services.telegram_service import extract_join_target, telegram_service

logger = logging.getLogger(__name__)


async def _fetch_project_sources(db: AsyncSession, project_id: int) -> list[TelegramSource]:
    """Return enabled TelegramSources for the project."""
    result = await db.execute(
        select(TelegramSource).where(
            TelegramSource.project_id == project_id,
            TelegramSource.is_enabled.is_(True),
        )
    )
    return result.scalars().all()


# Conservative humanization envelope between actions. The rate
# limiter already sleeps at least its own min_delay; this is the
# additional "I'm reading / thinking" jitter.
HUMAN_JITTER = {
    "read_min": 2.0,
    "read_max": 8.0,
    "typing_min": 5.0,
    "typing_max": 15.0,
    "reaction_min": 3.0,
    "reaction_max": 8.0,
    "between_actions_min": 5.0,
    "between_actions_max": 30.0,
}


def get_warmup_config(account_age_days: int) -> Dict:
    """Return the warm-up day config for an account of given age.

    Delegates to :func:`warmup_day_for` in safety_guidelines, which
    returns the most recent defined day. Each day's ``actions``
    dict drives what the warmup runner is allowed to do.
    """
    day = warmup_day_for(account_age_days)
    return {
        "day": day.day,
        "phase": day.phase,
        "actions": day.actions,
        "notes": day.notes,
        "max_dms": day.actions.get("send", 0),
    }


async def simulate_typing(
    client,
    target_username: str,
    duration: Optional[int] = None,
) -> bool:
    """Send a ``typing`` action then a ``cancel`` after a delay."""
    try:
        await client.send_chat_action(target_username, "typing")
        if duration is None:
            duration = random.randint(
                int(HUMAN_JITTER["typing_min"]), int(HUMAN_JITTER["typing_max"])
            )
        await asyncio.sleep(duration)
        await client.send_chat_action(target_username, "cancel")
        return True
    except Exception as e:
        logger.error("Typing simulation failed: %s", e)
        return False


async def simulate_reading(
    client,
    chat_username: str,
    duration: Optional[int] = None,
) -> bool:
    """Mark a chat as read and sleep for a human-like interval."""
    try:
        if duration is None:
            duration = random.randint(
                int(HUMAN_JITTER["read_min"]), int(HUMAN_JITTER["read_max"])
            )
        await client.read_chat_history(chat_username)
        await asyncio.sleep(duration)
        return True
    except Exception as e:
        logger.error("Reading simulation failed: %s", e)
        return False


async def send_random_reaction(
    client,
    chat_username: str,
    message_id: Optional[int] = None,
    account_id: Optional[int] = None,
    account_age_days: int = 30,
) -> bool:
    """Send a random reaction. Goes through the rate limiter."""
    try:
        if account_id is not None:
            try:
                await rate_limiter.acquire(
                    "reaction",
                    account_id,
                    account_age_days=account_age_days,
                )
            except (NewbornAccountError, RateLimitExceeded, SkipAction) as exc:
                logger.info("Skipping reaction in warmup: %s", exc)
                return False
        reactions = ["👍", "❤️", "🔥", "👏", "🎉"]
        reaction = random.choice(reactions)

        if message_id is None:
            async for message in client.get_chat_history(chat_username, limit=1):
                message_id = message.id
                break

        if message_id:
            await client.send_reaction(chat_username, message_id, reaction)
            await asyncio.sleep(
                random.randint(
                    int(HUMAN_JITTER["reaction_min"]),
                    int(HUMAN_JITTER["reaction_max"]),
                )
            )
            return True
        return False
    except Exception as e:
        logger.error("Reaction failed: %s", e)
        return False


async def simulate_human_behavior(
    client,
    action_type: str,
    account: Account,
    count: int = 3,
) -> Dict:
    """Drive a small loop of human-like actions on the dialog list."""
    result = {"action_type": action_type, "success_count": 0, "errors": []}
    try:
        chats = []
        async for dialog in client.get_dialogs(limit=10):
            chats.append(dialog.chat)
            if len(chats) >= count:
                break

        account_age_days = (datetime.utcnow() - (account.created_at or datetime.utcnow())).days

        await asyncio.sleep(
            random.uniform(
                HUMAN_JITTER["between_actions_min"],
                HUMAN_JITTER["between_actions_max"],
            )
        )

        for chat in chats:
            try:
                chat_id = chat.username or chat.id
                if action_type == "typing":
                    await simulate_typing(client, chat_id)
                    result["success_count"] += 1
                elif action_type == "read":
                    await simulate_reading(client, chat_id)
                    result["success_count"] += 1
                elif action_type == "react":
                    await send_random_reaction(
                        client,
                        chat_id,
                        account_id=account.id,
                        account_age_days=account_age_days,
                    )
                    result["success_count"] += 1
                elif action_type == "all":
                    await simulate_typing(client, chat_id)
                    result["success_count"] += 1
                    await asyncio.sleep(random.uniform(5, 15))
                    await send_random_reaction(
                        client,
                        chat_id,
                        account_id=account.id,
                        account_age_days=account_age_days,
                    )
                    result["success_count"] += 1

                await asyncio.sleep(
                    random.uniform(
                        HUMAN_JITTER["between_actions_min"],
                        HUMAN_JITTER["between_actions_max"],
                    )
                )
            except Exception as e:
                result["errors"].append(f"{chat}: {e}")
    except Exception as e:
        result["errors"].append(f"General error: {e}")
    return result


async def join_safe_group(
    client,
    group_username: str,
    account: Account,
) -> bool:
    """Join a group, going through the shared rate limiter."""
    from app.core.safety_guidelines import effective_account_age_days
    try:
        await rate_limiter.acquire(
            "join",
            account.id,
            account_age_days=effective_account_age_days(account),
        )
    except (NewbornAccountError, RateLimitExceeded, SkipAction) as exc:
        logger.info("Skipping group join in warmup: %s", exc)
        return False
    try:
        await client.join_chat(extract_join_target(group_username))
        logger.info("Joined group: %s", group_username)
        await asyncio.sleep(random.uniform(30, 90))
        return True
    except FloodWait as e:
        logger.warning("FloodWait joining %s: %ss, skipping", group_username, e.value)
        await asyncio.sleep(min(e.value, 300))
        return False
    except Exception as e:
        logger.error("Failed to join %s: %s", group_username, e)
        return False


async def run_account_warmup(
    db: AsyncSession,
    account: Account,
) -> Dict:
    """Run the warm-up cycle for one account.

    Safety fixes (2026-06):
    - warmup_level rises at most once per 20 h (not once per run).
      Previously every manual/auto run added +1, so an account could
      reach "infant" phase within hours and start DMing.
    - Reactions removed from the warmup loop. The old code picked
      the top-10 dialogs at random and reacted to the last message
      in each — a classic bot pattern that Telegram's ML detects.
    - Reading is now limited to the account's OWN warmup-pool sources
      (channels it has been assigned to join). Calling get_dialogs()
      and reading random chats looks unnatural on a fresh account.
    """
    result = {
        "account_id": account.id,
        "phone_number": account.phone_number,
        "actions": [],
        "started_at": datetime.utcnow().isoformat(),
    }
    try:
        if not account.session_string:
            result["status"] = "failed"
            result["error"] = "account_not_authorized: no session_string"
            result["completed_at"] = datetime.utcnow().isoformat()
            return result
        client = await telegram_service.get_client(account)

        account_age = (
            (datetime.utcnow() - account.created_at).days
            if account.created_at
            else 0
        )
        config = get_warmup_config(account_age)
        result["warmup_phase"] = config["phase"]
        result["warmup_day"] = config["day"]
        result["warmup_notes"] = config["notes"]
        actions_today = config["actions"]

        sm = get_safety_manager(db)

        # ── Reading: only sources the account has already joined ──────────
        # Previously we called get_dialogs() and read whatever 10 chats
        # happened to be on top — including old spam, DMs with strangers,
        # etc. A fresh account "reading" random dialogs is a bot signal.
        # Now we only scroll through channels that the account has been
        # explicitly assigned to via the warmup pool.
        if actions_today.get("read", 0) > 0:
            joined_ids: list[int] = account.joined_source_ids or []
            if joined_ids:
                sources_result = await db.execute(
                    select(TelegramSource).where(
                        TelegramSource.id.in_(joined_ids[:5]),
                        TelegramSource.is_enabled.is_(True),
                    )
                )
                sources_to_read = sources_result.scalars().all()
                read_ok = 0
                for src in sources_to_read:
                    target = src.normalized_link
                    if not target:
                        continue
                    ok = await simulate_reading(client, target)
                    if ok:
                        read_ok += 1
                        await sm.apply_anti_ban_delay("read")
                        await sm.log_action(
                            project_id=account.project_id,
                            action_type="read",
                            account_id=account.id,
                            result="success",
                        )
                    await asyncio.sleep(random.uniform(
                        HUMAN_JITTER["between_actions_min"],
                        HUMAN_JITTER["between_actions_max"],
                    ))
                result["actions"].append({"type": "read_channels", "success": read_ok})
            else:
                result["actions"].append({
                    "type": "read_channels",
                    "success": 0,
                    "note": "no joined sources yet — assign a warmup pool first",
                })

        # ── Reactions: DISABLED in warmup ─────────────────────────────────
        # Sending reactions to the last message in random dialogs is a
        # textbook bot pattern. Reactions are only safe when the account
        # has been in the channel for a while and chooses which post to
        # react to naturally. Removed entirely from automated warmup.
        # (The WARMUP_SCHEDULE still defines reaction counts for future
        # manual/selective use; we just don't execute them here.)

        # ── Group joins: from light_messaging phase onward (day 5+) ──────
        # IMPORTANT: Joins must NOT happen in "setup" phase (days 1-4).
        # Joining groups in the first days is a primary bot-detection signal.
        # Only accounts with real DB age >= 5 days are allowed to join.
        real_age_days = (
            (datetime.utcnow() - account.created_at).days
            if account.created_at
            else 0
        )
        joins_allowed = (
            config["phase"] not in ("setup",)
            and real_age_days >= 5
            and actions_today.get("join", 0) > 0
        )
        if joins_allowed:
            assignment = account.warmup_assignment or {}
            assigned_ids: list[int] = assignment.get("source_ids") or []

            if assigned_ids:
                sources_to_join_result = await db.execute(
                    select(TelegramSource).where(
                        TelegramSource.id.in_(assigned_ids),
                        TelegramSource.is_enabled.is_(True),
                    )
                )
                candidate_sources = [
                    s for s in sources_to_join_result.scalars().all()
                    if s.id not in (account.joined_source_ids or []) and s.normalized_link
                ]
            else:
                project_sources = await _fetch_project_sources(db, account.project_id)
                candidate_sources = [
                    s for s in project_sources
                    if s.id not in (account.joined_source_ids or []) and s.normalized_link
                ]

            to_join = candidate_sources[:1]  # max 1 per run — be conservative
            for source in to_join:
                target = source.normalized_link
                success = await join_safe_group(client, target, account)
                result["actions"].append(
                    {"type": "join_group", "group": target, "success": success}
                )
                if success:
                    from sqlalchemy.orm.attributes import flag_modified
                    ids: list = list(account.joined_source_ids or [])
                    if source.id not in ids:
                        ids.append(source.id)
                        account.joined_source_ids = ids
                        flag_modified(account, "joined_source_ids")
                # Long pause between joins — Telegram is very sensitive here
                await asyncio.sleep(random.uniform(180, 480))

        # ── Bump warmup_level — at most once per 20 hours ─────────────────
        # Before this fix, every run added +1 regardless of how recently
        # the previous run happened. With auto-warmup every 4-8 h, an
        # account could accumulate 4-6 levels in one real day, exit the
        # "newborn" phase and start sending DMs the same day it was added.
        now = datetime.utcnow()
        last_active = account.last_active
        hours_since_last = (
            (now - last_active).total_seconds() / 3600
            if last_active
            else 999
        )
        level_bumped = False
        if hours_since_last >= 20:
            account.warmup_level = min(30, (account.warmup_level or 0) + 1)
            level_bumped = True

        account.last_active = now

        if account.status == AccountStatus.NEW:
            account.status = AccountStatus.WARMING
        if account.warmup_level >= 14 and account.status != AccountStatus.PRODUCTION:
            account.status = AccountStatus.PRODUCTION

        await db.commit()

        result["completed_at"] = now.isoformat()
        result["status"] = "completed"
        result["warmup_level"] = account.warmup_level
        result["level_bumped"] = level_bumped
    except Exception as e:
        result["error"] = str(e)
        result["status"] = "failed"
        result["completed_at"] = datetime.utcnow().isoformat()
    return result


async def run_all_accounts_warmup(
    db: AsyncSession, project_id: int = 1
) -> List[Dict]:
    """Run warm-up for every NEW / WARMING account in the project."""
    result = await db.execute(
        select(Account)
        .where(
            Account.status.in_([AccountStatus.NEW, AccountStatus.WARMING]),
            Account.project_id == project_id,
        )
        .options(selectinload(Account.proxy))
    )
    accounts = result.scalars().all()

    results = []
    for account in accounts:
        warmup_result = await run_account_warmup(db, account)
        results.append(warmup_result)
        # Long pause between accounts — prevents Telegram from seeing correlated
        # activity patterns across multiple accounts at the same timestamp.
        await asyncio.sleep(random.uniform(60, 180))

    # Inter-account warm-up: accounts DM each other using human-like
    # scripts. Far more convincing than channel-reading alone. Best-effort,
    # never fails the warmup. Random round rotates partners so over several
    # runs every account chats with every other ("each with each").
    try:
        from app.services.warmup_conversations import run_warmup_conversations

        convo = await run_warmup_conversations(
            project_id=project_id, round_index=random.randint(0, 11)
        )
        results.append({"type": "account_conversations", **convo})
    except Exception as exc:  # noqa: BLE001
        logger.warning("warmup conversations step failed: %s", exc)

    return results


def get_warmup_schedule() -> Dict:
    """Return the full schedule — kept for the ``/warmup-status`` endpoint."""
    return {
        f"day_{d.day}": {
            "day": d.day,
            "phase": d.phase,
            "max_dms_per_day": d.actions.get("send", 0),
            "actions": [
                f"read: ≤ {d.actions.get('read', 0)}",
                f"join: ≤ {d.actions.get('join', 0)}",
                f"send: ≤ {d.actions.get('send', 0)}",
                f"comment: ≤ {d.actions.get('comment', 0)}",
                f"reaction: ≤ {d.actions.get('reaction', 0)}",
            ],
            "notes": d.notes,
        }
        for d in WARMUP_SCHEDULE.values()
    }


def get_warmup_status(account: Account) -> Dict:
    """Return a snapshot of the account's current warm-up state.

    Driven by ``phase_for_age_days`` from safety_guidelines — the
    same source of truth that the rate limiter uses.
    """
    age_days = (datetime.utcnow() - account.created_at).days if account.created_at else 0
    level = account.warmup_level or 0
    phase = phase_for_age_days(age_days)
    day = warmup_day_for(age_days)
    return {
        "account_id": account.id,
        "age_days": age_days,
        "warmup_level": level,
        "phase": phase.name,
        "phase_multiplier": phase.multiplier,
        "warmup_day": day.day,
        "warmup_phase": day.phase,
        "max_dms_today": day.actions.get("send", 0),
        "max_reactions_today": day.actions.get("reaction", 0),
        "max_joins_today": day.actions.get("join", 0),
        "next_phase_in_days": max(0, phase.max_age_days - age_days)
        if phase.max_age_days < 10**9
        else None,
        "recommendations": [
            f"Account age: {age_days} days",
            f"Warmup level: {level}/30",
            f"Current phase: {phase.name} (×{phase.multiplier} of full quota)",
            f"Today's envelope: {day.actions}",
            day.notes,
        ],
    }
