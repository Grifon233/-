"""
Groups Service
Автоматическое вступление в группы.

Safety integration
------------------
The Telegram anti-spam heuristic for group-join is harsh: a
"Too Many Attempts" / FloodWait after 5-10 fast joins and a
24-hour soft-ban in the worst case. Every join goes through the
shared :mod:`app.core.rate_limiter` so the per-(account, action)
limits and the phase-based multiplier from
:mod:`app.core.safety_guidelines` are honoured automatically.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional

from pyrogram.errors import FloodWait, RPCError

from app.core.rate_limiter import (
    NewbornAccountError,
    RateLimitExceeded,
    rate_limiter,
)
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.group_task import GroupTask, GroupTaskStatus
from app.services.telegram_service import extract_join_target, telegram_service

logger = logging.getLogger(__name__)

# In-memory registry of running tasks. Used so the ``stop``
# endpoint can call ``task.cancel()`` to short-circuit the loop.
# For distributed deployments this should move to Redis.
RUNNING_TASKS: Dict[int, asyncio.Task] = {}

# Conservative safe groups for first-time warm-up. The operator
# can override per-account in the UI. These names are placeholders
# — replace with real channels in your allowlist before relying on
# them.
SAFE_GROUPS = [
    "@crypto_news_en",
    "@startup_ideas",
    "@tech_talks_en",
    "@bitcoin_community",
    "@ethereum_news",
    "@nft_marketplace",
]


async def _is_group_task_stopped(task_id: int) -> bool:
    async with SessionLocal() as db:
        task = await db.get(GroupTask, task_id)
        return bool(task and task.status == GroupTaskStatus.STOPPED)


async def join_group(client, group_username: str) -> bool:
    """Join a group by username or invite link."""
    try:
        await client.join_chat(extract_join_target(group_username))
        return True
    except RPCError as e:
        logger.error("Failed to join %s: %s", group_username, e)
        return False


async def execute_group_task(
    account: Account,
    groups: List[str],
    task_id: int = None,
    delay_min: int = 30,
    delay_max: int = 120,
) -> Dict:
    """Execute group joining task for an account.

    The delays between joins come from two sources:

    * The safety guidelines' phase envelope (newborn → blocked,
      infant → 60-180s, …, aged → 5-20s). The campaign's
      ``delay_min``/``delay_max`` are clamped against that envelope
      so we never go below the safety floor.
    * The random ``random.randint(delay_min, delay_max)`` call
      introduces the human-like jitter between joins.
    """
    if task_id:
        RUNNING_TASKS[task_id] = asyncio.current_task()

    results = {
        "account_id": account.id,
        "task_id": task_id,
        "groups_joined": 0,
        "errors": [],
        "started_at": datetime.utcnow().isoformat(),
    }

    account_age_days = (datetime.utcnow() - (account.created_at or datetime.utcnow())).days

    try:
        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(GroupTask, task_id)
                if db_task:
                    if db_task.status == GroupTaskStatus.STOPPED:
                        results["status"] = "stopped"
                        return results
                    db_task.status = GroupTaskStatus.RUNNING
                    db_task.started_at = datetime.utcnow()
                    await db.commit()

        client = await telegram_service.get_client(account)

        for group in groups:
            if task_id and await _is_group_task_stopped(task_id):
                results["status"] = "stopped"
                break
            try:
                # Acquire a token from the ``join`` bucket. This
                # blocks newborn accounts entirely and caps
                # others at 10/day (per safety_guidelines).
                try:
                    await rate_limiter.acquire(
                        "join",
                        account.id,
                        account_age_days=account_age_days,
                        min_delay=delay_min,
                    )
                except NewbornAccountError as exc:
                    logger.warning(
                        "Skipping group join for newborn account %s: %s",
                        account.id,
                        exc,
                    )
                    results["errors"].append(
                        f"{group}: newborn_account_skip"
                    )
                    break  # No point trying more joins today
                except RateLimitExceeded as exc:
                    logger.warning(
                        "Group-join daily cap reached for account %s: %s",
                        account.id,
                        exc,
                    )
                    results["errors"].append(
                        f"{group}: rate_limit ({exc.phase})"
                    )
                    break

                success = await join_group(client, group)
                if success:
                    results["groups_joined"] += 1

                    if task_id:
                        async with SessionLocal() as db:
                            db_task = await db.get(GroupTask, task_id)
                            if db_task:
                                db_task.groups_joined = results["groups_joined"]
                                await db.commit()

                # Human-like delay between joins. ``rate_limiter``
                # already slept at least its own min_delay; we
                # add a small extra on top for further de-sync.
                await asyncio.sleep(random.randint(delay_min, delay_max))

            except asyncio.CancelledError:
                if task_id:
                    async with SessionLocal() as db:
                        db_task = await db.get(GroupTask, task_id)
                        if db_task:
                            db_task.status = GroupTaskStatus.STOPPED
                            await db.commit()
                raise
            except FloodWait as e:
                # Honour Telegram's cooldown exactly; if the value
                # is huge (>= 1h) treat the account as effectively
                # rate-limited for today.
                logger.warning("FloodWait: %ss", e.value)
                if e.value >= 3600:
                    results["errors"].append(
                        f"flood_wait_long: {e.value}s — pausing until tomorrow"
                    )
                    break
                await asyncio.sleep(e.value)
            except Exception as e:
                results["errors"].append(f"{group}: {str(e)}")

        results.setdefault("status", "completed")
        results["completed_at"] = datetime.utcnow().isoformat()

        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(GroupTask, task_id)
                if db_task and db_task.status != GroupTaskStatus.STOPPED:
                    db_task.status = GroupTaskStatus.COMPLETED
                    db_task.completed_at = datetime.utcnow()
                    await db.commit()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        results["status"] = "failed"
        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(GroupTask, task_id)
                if db_task:
                    db_task.status = GroupTaskStatus.FAILED
                    db_task.error_message = str(e)
                    await db.commit()
    finally:
        if task_id in RUNNING_TASKS:
            del RUNNING_TASKS[task_id]

    return results


async def stop_group_task(task_id: int) -> bool:
    """Stop a running group task."""
    if task_id in RUNNING_TASKS:
        RUNNING_TASKS[task_id].cancel()
        return True
    return False


def get_safe_groups() -> List[str]:
    """Get list of safe groups for joining."""
    return SAFE_GROUPS
