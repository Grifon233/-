"""
Mass Reactions Service
Автоматические реакции на посты в каналах/группах

Based on:
- ItsOrv/Telegram-Panel (bulk operations with semaphore)
  https://github.com/ItsOrv/Telegram-Panel
- JohnnyC0rp/TelegramAutoReacter (simple reaction handler)
  https://github.com/JohnnyC0rp/TelegramAutoReacter
- VoxHash/Telegram-Multi-Account-Message-Sender (rate limiting)

Key patterns:
- client.send_reaction(channel, message_id, emoji) pattern
- Bulk operation with asyncio semaphore
- FloodWaitError handling
- Multi-account round-robin
"""

import asyncio
import json
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pyrogram.errors import FloodWait, ReactionInvalid

from app.models.account import Account, AccountStatus
from app.models.reaction_task import ReactionTask, ReactionTaskStatus
from app.services.telegram_service import telegram_service
from app.core.rate_limiter import rate_limiter, RateLimitExceeded, NewbornAccountError, SkipAction
from app.core.safety_guidelines import effective_account_age_days
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Global registry for running tasks to allow stopping them
RUNNING_TASKS: Dict[int, asyncio.Task] = {}

# Constants from Telegram-Panel
MAX_CONCURRENT_OPERATIONS = 5
DEFAULT_DELAY_MIN = 2.0
DEFAULT_DELAY_MAX = 5.0


class ReactionType:
    """Telegram reaction types."""
    THUMBS_UP = "👍"
    THUMBS_DOWN = "👎"
    HEART = "❤️"
    FIRE = "🔥"
    CLAP = "👏"
    THINKING = "🤔"
    EYES = "👀"
    PARTY = "🎉"


# Settings from VoxHash pattern
REACTION_SETTINGS = {
    "enabled": True,
    "min_delay": 5,
    "max_delay": 30,
    "max_per_day": 500,
    "reaction_chance": 0.7,  # 70% chance to react
}

DEFAULT_REACTIONS = [
    ReactionType.THUMBS_UP,
    ReactionType.HEART,
    ReactionType.FIRE,
    ReactionType.CLAP,
]


async def _is_reaction_task_stopped(task_id: int) -> bool:
    async with SessionLocal() as db:
        task = await db.get(ReactionTask, task_id)
        return bool(task and task.status == ReactionTaskStatus.STOPPED)


def is_session_revoked_error(error: Exception) -> bool:
    """Check if error indicates session revocation."""
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()
    return any(keyword in error_msg for keyword in [
        'session', 'revoked', 'not logged in', 'auth key',
        'authorization', 'key is not registered', 'unregistered'
    ]) or any(keyword in error_type for keyword in ['revoked', 'auth'])


async def send_reaction(
    client,
    channel: str,
    message_id: int,
    reaction: str,
    account_id: int | None = None,
    account_age_days: int = 30,
) -> bool:
    """
    Send a reaction to a message.

    From JohnnyC0rp/TelegramAutoReacter pattern:
    app.send_reaction(chat_id, message_id, REACTION)
    """
    # The shared rate limiter is the only thing that prevents a
    # reaction run + a campaign send + a group-join from all
    # hitting the same account in the same second. The phase-
    # aware limits come from app.core.safety_guidelines — newborn
    # accounts (0-3 days) are blocked, infant accounts are
    # throttled to 5% of an aged account.
    if account_id is not None:
        try:
            await rate_limiter.acquire(
                "reaction",
                account_id,
                account_age_days=account_age_days,
            )
        except SkipAction:
            logger.info("Humanization skip for reaction on account %s", account_id)
            return False
        except NewbornAccountError as exc:
            logger.warning(
                "Skipping reaction for newborn account %s: %s", account_id, exc
            )
            return False
        except RateLimitExceeded as exc:
            logger.warning(
                "Daily reaction limit reached for account %s (phase=%s)",
                account_id,
                exc.phase,
            )
            return False
    try:
        # Use client.send_reaction() - this is the standard Pyrogram method
        await client.send_reaction(channel, message_id, reaction)
        return True
    except ReactionInvalid:
        logger.warning(f"Invalid reaction: {reaction}")
        return False
    except Exception as e:
        logger.error(f"Failed to send reaction: {e}")
        return False


async def get_channel_posts(
    client,
    channel_username: str,
    limit: int = 50
) -> List:
    """Get recent posts from a channel."""
    try:
        messages = []
        async for message in client.get_chat_history(channel_username, limit=limit):
            # Skip messages without text (photos, videos, etc.)
            if message.text or message.caption:
                messages.append(message)
        return messages
    except Exception as e:
        logger.error(f"Failed to get posts from {channel_username}: {e}")
        return []


async def react_to_channel(
    account: Account,
    channel: str,
    reaction_types: List[str],
    posts_limit: int = 20
) -> Dict:
    """
    React to posts in a single channel.

    Based on Telegram-Panel bulk_reaction patterns.
    """
    result = {
        "account_id": account.id,
        "channel": channel,
        "posts_found": 0,
        "reactions_sent": 0,
        "errors": []
    }

    try:
        client = await telegram_service.get_client(account)

        # Get recent posts
        posts = await get_channel_posts(client, channel, limit=posts_limit)
        result["posts_found"] = len(posts)

        for post in posts:
            # Random chance to react (from VoxHash pattern)
            if random.random() > REACTION_SETTINGS["reaction_chance"]:
                continue

            # Pick random reaction
            reaction = random.choice(reaction_types)

            # Send reaction
            success = await send_reaction(client, channel, post.id, reaction)
            if success:
                result["reactions_sent"] += 1

            # Random delay (human-like behavior)
            delay = random.randint(
                REACTION_SETTINGS["min_delay"],
                REACTION_SETTINGS["max_delay"]
            )
            await asyncio.sleep(delay)

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Error reacting to {channel}: {e}")

    return result


async def mass_react_for_account(
    account: Account,
    channels: List[str],
    reaction_types: List[str] = None,
    task_id: int = None,
    min_delay: int = None,
    max_delay: int = None,
    posts_limit: int = 20,
    max_reactions: int = None,
) -> Dict:
    """
    Run mass reactions for a single account across multiple channels.

    From ItsOrv/Telegram-Panel execute_bulk_operation pattern:
    - Semaphore for concurrency control
    - Counter lock for thread-safe counting
    - FloodWaitError handling
    """
    if reaction_types is None:
        reaction_types = DEFAULT_REACTIONS

    if min_delay is None:
        min_delay = REACTION_SETTINGS["min_delay"]
    if max_delay is None:
        max_delay = REACTION_SETTINGS["max_delay"]

    # Register task in global dict to allow stopping
    if task_id:
        RUNNING_TASKS[task_id] = asyncio.current_task()

    results = {
        "account_id": account.id,
        "task_id": task_id,
        "channels_processed": 0,
        "reactions_sent": 0,
        "errors": [],
        "started_at": datetime.utcnow().isoformat(),
    }

    try:
        # Update task status in DB
        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(ReactionTask, task_id)
                if db_task:
                    if db_task.status == ReactionTaskStatus.STOPPED:
                        results["status"] = "stopped"
                        return results
                    db_task.status = ReactionTaskStatus.RUNNING
                    db_task.started_at = datetime.utcnow()
                    await db.commit()

        client = await telegram_service.get_client(account)

        for channel in channels:
            if task_id and await _is_reaction_task_stopped(task_id):
                results["status"] = "stopped"
                break
            try:
                posts = await get_channel_posts(client, channel, limit=posts_limit)

                for post in posts:
                    if task_id and await _is_reaction_task_stopped(task_id):
                        results["status"] = "stopped"
                        break
                    if max_reactions and results["reactions_sent"] >= max_reactions:
                        results["status"] = "completed"
                        break
                    # Random chance to react
                    if random.random() > REACTION_SETTINGS["reaction_chance"]:
                        continue

                    # Pick and send reaction
                    reaction = random.choice(reaction_types)
                    account_age_days = effective_account_age_days(account)
                    success = await send_reaction(
                        client,
                        channel,
                        post.id,
                        reaction,
                        account_id=account.id,
                        account_age_days=account_age_days,
                    )

                    if success:
                        results["reactions_sent"] += 1
                        
                        # Update progress in DB every 5 reactions
                        if task_id and results["reactions_sent"] % 5 == 0:
                            async with SessionLocal() as db:
                                db_task = await db.get(ReactionTask, task_id)
                                if db_task:
                                    db_task.reactions_used = results["reactions_sent"]
                                    await db.commit()

                    # Random delay between reactions
                    delay = random.uniform(min_delay, max_delay)
                    await asyncio.sleep(delay)

                results["channels_processed"] += 1
                if results.get("status") in ("stopped", "completed"):
                    break

            except asyncio.CancelledError:
                logger.info(f"Task {task_id} cancelled")
                if task_id:
                    async with SessionLocal() as db:
                        db_task = await db.get(ReactionTask, task_id)
                        if db_task:
                            db_task.status = ReactionTaskStatus.STOPPED
                            db_task.reactions_used = results["reactions_sent"]
                            await db.commit()
                raise
            except FloodWait as e:
                logger.warning(f"FloodWait for {channel}: {e.value}s")
                await asyncio.sleep(e.value)
            except Exception as e:
                results["errors"].append(f"{channel}: {str(e)}")

        results["completed_at"] = datetime.utcnow().isoformat()
        results.setdefault("status", "completed")

        # Final DB update
        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(ReactionTask, task_id)
                if db_task and db_task.status != ReactionTaskStatus.STOPPED:
                    db_task.status = ReactionTaskStatus.COMPLETED
                    db_task.completed_at = datetime.utcnow()
                    db_task.reactions_used = results["reactions_sent"]
                    await db.commit()

    except asyncio.CancelledError:
        # Already handled above, but just in case
        pass
    except Exception as e:
        results["errors"].append(f"Account error: {str(e)}")
        results["status"] = "failed"
        
        if task_id:
            async with SessionLocal() as db:
                db_task = await db.get(ReactionTask, task_id)
                if db_task:
                    db_task.status = ReactionTaskStatus.FAILED
                    db_task.error_message = str(e)
                    db_task.reactions_used = results["reactions_sent"]
                    await db.commit()

    finally:
        if task_id in RUNNING_TASKS:
            del RUNNING_TASKS[task_id]

    return results


async def stop_reaction_task(task_id: int) -> bool:
    """Stop a running reaction task."""
    if task_id in RUNNING_TASKS:
        RUNNING_TASKS[task_id].cancel()
        return True
    return False


async def mass_react_multi_account(
    accounts: List[Account],
    channels: List[str],
    reaction_types: List[str] = None,
) -> List[Dict]:
    """
    Run mass reactions across multiple accounts.

    From Telegram-Panel bulk pattern with semaphore.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPERATIONS)
    counter_lock = asyncio.Lock()
    results = []

    async def react_with_account(account):
        async with semaphore:
            result = await mass_react_for_account(
                account, channels, reaction_types
            )
            async with counter_lock:
                results.append(result)
            return result

    tasks = [react_with_account(acc) for acc in accounts]
    await asyncio.gather(*tasks, return_exceptions=True)

    return results


async def monitor_channel_for_new_posts(
    account: Account,
    channel: str,
    reaction_types: List[str],
    duration_minutes: int = 60,
) -> Dict:
    """
    Monitor a channel for new posts and react to them.

    From Telegram-Panel monitor mode pattern.
    """
    results = {
        "account_id": account.id,
        "channel": channel,
        "posts_seen": 0,
        "reactions_sent": 0,
        "started_at": datetime.utcnow().isoformat(),
    }

    try:
        client = await telegram_service.get_client(account)

        # Track the highest message id we've already reacted to. Comparing
        # against the MAX (not the last value of the loop variable) is what
        # makes "only react to genuinely new posts" correct — otherwise the
        # oldest of each batch overwrote the marker and we re-reacted to the
        # same posts on every poll.
        last_message_id = 0
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(minutes=duration_minutes)

        while datetime.utcnow() < end_time:
            try:
                # Get latest messages
                highest_seen = last_message_id
                async for message in client.get_chat_history(channel, limit=5):
                    if message.id > last_message_id:
                        highest_seen = max(highest_seen, message.id)
                        results["posts_seen"] += 1

                        # React to new post
                        if random.random() < REACTION_SETTINGS["reaction_chance"]:
                            reaction = random.choice(reaction_types)
                            account_age_days = (
                                (datetime.utcnow() - (account.created_at or datetime.utcnow())).days
                            )
                            success = await send_reaction(
                                client,
                                channel,
                                message.id,
                                reaction,
                                account_id=account.id,
                                account_age_days=account_age_days,
                            )
                            if success:
                                results["reactions_sent"] += 1

                # Advance the marker so the next poll only reacts to posts
                # newer than everything we've already seen this run.
                last_message_id = highest_seen

                # Wait before checking again
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(60)

        results["completed_at"] = datetime.utcnow().isoformat()
        results["status"] = "completed"

    except Exception as e:
        results["error"] = str(e)
        results["status"] = "failed"

    return results


def get_available_reactions() -> List[str]:
    """Get list of available reaction emojis."""
    return [
        ReactionType.THUMBS_UP,
        ReactionType.THUMBS_DOWN,
        ReactionType.HEART,
        ReactionType.FIRE,
        ReactionType.CLAP,
        ReactionType.THINKING,
        ReactionType.EYES,
        ReactionType.PARTY,
    ]
