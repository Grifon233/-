"""Neuro-commenting Celery tasks.

Reads recent posts from a Telegram channel's linked discussion
group, generates an AI draft, then publishes it (either
automatically, after a moderation step, or with a manual
approval).

Safety integration
------------------
Every Telegram call goes through the shared
:mod:`app.core.rate_limiter`, so :mod:`app.core.safety_guidelines`
is the single source of truth. Specifically:

* ``process_post`` calls ``rate_limiter.acquire("comment", ...,
  account_age_days=...)`` before reading the discussion thread.
* ``publish_draft`` does the same before posting.
* Newborn accounts raise :class:`NewbornAccountError`; we log and
  skip the recipient.
* Daily cap raises :class:`RateLimitExceeded`; we log and stop the
  current source.

This task also uses :func:`app.core.celery_app.async_run` instead
of bare ``asyncio.run`` so the loop driver lives in one place.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime
from typing import List

from pyrogram.enums import ChatType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.celery_app import async_run, celery_app
from app.core.rate_limiter import (
    NewbornAccountError,
    RateLimitExceeded,
    SkipAction,
    rate_limiter,
)
from app.core.safety_guidelines import phase_for_age_days, effective_account_age_days, warmup_day_for
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.comment_task import (
    CommentDraft,
    CommentLog,
    CommentPolicy,
    CommentSourceStateStatus,
    CommentTask,
    CommentTaskSourceState,
    CommentTaskStatus,
    CommentTargetMode,
)
from app.models.telegram_source import TelegramSource
from app.models.telegram_source import TelegramSourceType
from app.services.ai_provider_service import get_ai_client, get_provider_config
from app.services.telegram_service import telegram_service
from app.core.config import settings

logger = logging.getLogger(__name__)

TME_PUBLIC_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})(?:/.*)?$",
    re.IGNORECASE,
)


def telegram_chat_target(source_or_link) -> str:
    """Return the value Pyrogram expects for a public source.

    The UI stores public sources as ``https://t.me/username`` because that is
    human-friendly. Pyrogram's ``get_chat`` / ``get_chat_history`` expect the
    username itself, while invite links must stay as full links.
    """
    link = getattr(source_or_link, "normalized_link", source_or_link) or ""
    link = str(link).strip()
    if not link:
        return link
    if "/+" in link or "/joinchat/" in link:
        return link
    if link.startswith("@"):
        return link[1:]
    match = TME_PUBLIC_RE.fullmatch(link)
    if match:
        return match.group(1)
    return link


def _is_human_comment(message) -> bool:
    """Return True only for a genuine message written by a real person.

    This is the filter that stops the AI from "replying" to the wrong
    thing. In a discussion group the most recent messages are very often
    NOT human comments — they are:

    * service/system messages (someone joined, a post was pinned, the
      "подпишитесь после вступления" auto-notice);
    * the channel's own auto-forwarded post (no ``from_user``, it has a
      ``sender_chat``);
    * messages posted by an anonymous admin "as the channel";
    * bots;
    * ads cross-posted/forwarded from another channel.

    Building the AI context from those produced the bad drafts the
    operator saw. We keep only real, non-empty, human-authored text.
    """
    # ``service`` is a populated enum for join/pin/etc. messages.
    if getattr(message, "service", None):
        return False
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        # No real author → channel auto-post / anonymous admin.
        return False
    if getattr(from_user, "is_bot", False):
        return False
    if getattr(message, "forward_from_chat", None) is not None:
        # Forwarded from a channel → almost always an ad / cross-promo.
        return False
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    if not text:
        return False
    if _looks_like_ad(text):
        return False
    return True


# Promo/spam markers seen in real beauty/tattoo chats. Messages that
# contain a link or one of these are ads, not genuine conversation, and
# replying to them produced the bad drafts the operator reported
# ("доход в интернете от 15000 в день", "подпишитесь на канал @...").
_AD_LINK_MARKERS = ("http://", "https://", "t.me/", "www.", "wa.me/", "joinchat")
_AD_TEXT_MARKERS = (
    "подпишись", "подпишитесь", "подписаться на канал", "вступайте",
    "акция", "скидк", "реклам", "доход", "зарабат", "заработок",
    "набираю", "набор в команду", "в день", "легально", "ваканси",
    "куплю", "продам", "розыгрыш", "халяв", "промокод", "инвест",
)


def _looks_like_ad(text: str) -> bool:
    lowered = text.lower()
    if any(m in lowered for m in _AD_LINK_MARKERS):
        return True
    hits = sum(1 for m in _AD_TEXT_MARKERS if m in lowered)
    # One strong marker like "подпишитесь на канал" is enough; otherwise
    # require two weaker hits so a normal sentence mentioning e.g. "в день"
    # in passing isn't dropped.
    strong = ("подписаться на канал", "акция на рекламу", "доход", "заработок", "промокод", "розыгрыш")
    if any(s in lowered for s in strong):
        return True
    return hits >= 2


async def collect_recent_messages(client, chat_id: str, limit: int):
    async def _collect():
        items = []
        async for message in client.get_chat_history(chat_id, limit=limit):
            items.append(message)
        return items

    return await asyncio.wait_for(_collect(), timeout=45)


async def collect_discussion_replies(client, chat_id: str, post_id: int, limit: int):
    async def _collect():
        items = []
        async for message in client.get_discussion_replies(chat_id, post_id, limit=limit):
            items.append(message)
        return items

    return await asyncio.wait_for(_collect(), timeout=45)


@celery_app.task(name="app.tasks.commenting.run_neuro_commenting_task")
def run_neuro_commenting_task(task_id: int):
    """Run a single neuro-commenting task. See module docstring."""
    return async_run(_run_neuro_commenting_task(task_id))


async def _run_neuro_commenting_task(task_id: int) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(CommentTask).where(CommentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            logger.error("Comment task %s not found", task_id)
            return

        task.status = CommentTaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        await db.commit()

        try:
            await run_commenting_logic(db, task)
            task.status = CommentTaskStatus.COMPLETED
        except Exception as e:
            await db.rollback()
            logger.error("Error in comment task %s: %s", task_id, e)
            result = await db.execute(select(CommentTask).where(CommentTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return
            task.status = CommentTaskStatus.FAILED
            task.errors_count += 1

        task.finished_at = datetime.utcnow()
        await db.commit()


async def _account_age_days(account: Account) -> int:
    created_days = (datetime.utcnow() - (account.created_at or datetime.utcnow())).days
    status_value = account.status.value if hasattr(account.status, "value") else account.status
    if status_value == "production":
        return max(created_days, 30)
    return max(created_days, account.warmup_level or 0)


async def _safe_acquire_comment_token(
    account: Account, db: AsyncSession, task_id: int | None = None
) -> bool:
    """Try to acquire a ``comment`` rate-limiter token.

    Returns True if the action can proceed; False if we should skip
    (newborn account or daily cap exhausted). The decision is
    also recorded in the DB so the operator can see *why* a draft
    was skipped.
    """
    age_days = await _account_age_days(account)
    if task_id is not None:
        await log_action(
            db,
            task_id=task_id,
            account_id=account.id,
            action="waiting_comment_rate_limit",
            details={"account_age_days": age_days},
        )
    try:
        # 220s = 180s max sleep + 40s buffer for Redis ops.
        # Guards against stale Redis TCP connections that hang indefinitely.
        await asyncio.wait_for(
            rate_limiter.acquire("comment", account.id, account_age_days=age_days),
            timeout=220,
        )
        if task_id is not None:
            await log_action(
                db,
                task_id=task_id,
                account_id=account.id,
                action="comment_rate_limit_ready",
                details={"account_age_days": age_days},
            )
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "rate_limiter.acquire timed out for account %s — Redis may be hung, proceeding",
            account.id,
        )
        if task_id is not None:
            await log_action(
                db,
                task_id=task_id,
                account_id=account.id,
                action="comment_rate_limit_ready",
                details={"account_age_days": age_days, "warn": "timeout_fallthrough"},
            )
        # Reset rate limiter client so next call reconnects to Redis.
        rate_limiter._client = None
        rate_limiter._disabled = False
        return True
    except SkipAction:
        # Humanization: pretend the account scrolled past this post. No
        # token spent, action genuinely skipped (the point of the skip).
        if task_id is not None:
            await log_action(
                db,
                task_id=task_id,
                account_id=account.id,
                action="skipped_humanization",
            )
        logger.info("Humanization skip for comment on account %s", account.id)
        return False
    except NewbornAccountError as exc:
        await log_action(
            db,
            task_id=task_id,
            account_id=account.id,
            action="skipped_newborn",
            error_message=f"newborn_account phase={exc.phase}",
        )
        logger.info(
            "Skipping comment for newborn account %s (phase=%s)",
            account.id,
            exc.phase,
        )
        return False
    except RateLimitExceeded as exc:
        await log_action(
            db,
            task_id=task_id,
            account_id=account.id,
            action="skipped_rate_limit",
            error_message=f"phase={exc.phase} limit={exc.limit}",
        )
        logger.warning(
            "Comment daily cap reached for account %s (phase=%s, limit=%s)",
            account.id,
            exc.phase,
            exc.limit,
        )
        return False


async def run_commenting_logic(db: AsyncSession, task: CommentTask) -> None:
    """Main commenting logic.

    For each ``(source, account)`` pair:

    1. Acquire a ``comment`` rate-limiter token. Newborn
       accounts or accounts past their daily cap are skipped
       with a logged reason.
    2. Read the recent posts of the channel.
    3. For each candidate post, ``process_post`` generates an
       AI draft, runs the moderation filter, and either
       auto-publishes or saves it as ``pending``.
    """
    source_ids = task.source_ids or []
    account_ids = task.account_ids or []

    if not source_ids or not account_ids:
        logger.warning("Task %s: No sources or accounts configured", task.id)
        return

    await ensure_source_states(db, task)
    states_result = await db.execute(
        select(CommentTaskSourceState, TelegramSource)
        .join(TelegramSource, TelegramSource.id == CommentTaskSourceState.source_id)
        .where(
            CommentTaskSourceState.task_id == task.id,
            TelegramSource.id.in_(source_ids),
            CommentTaskSourceState.status.in_(
                [
                    CommentSourceStateStatus.PENDING,
                    CommentSourceStateStatus.FAILED,
                    CommentSourceStateStatus.JOIN_REQUESTED,
                ]
            ),
        )
        .order_by(CommentTaskSourceState.created_at.asc(), TelegramSource.id.asc())
    )
    state_rows = states_result.all()

    # Load accounts.
    accounts_result = await db.execute(
        select(Account)
        .options(selectinload(Account.proxy))
        .where(Account.id.in_(account_ids))
    )
    accounts = accounts_result.scalars().all()

    if not state_rows or not accounts:
        logger.warning("Task %s: No valid sources or accounts", task.id)
        return

    # Get AI client.
    try:
        provider_config = get_provider_config(task.provider)
        api_key = getattr(settings, provider_config["key_setting"], None)
        if not api_key:
            logger.error("No API key for provider %s", task.provider)
            return
        ai_client = get_ai_client(task.provider)
    except Exception as e:
        logger.error("AI client error: %s", e)
        return

    # Per-account comment counter for this run — enforces warmup-based caps.
    account_run_comments: dict[int, int] = {}

    for source_index, (source_state, source) in enumerate(state_rows):
        if task.comments_per_source <= 0:
            break

        # Check if task was stopped externally via API.
        await db.refresh(task)
        if task.status != CommentTaskStatus.RUNNING:
            logger.info("Task %s stopped externally, exiting loop", task.id)
            break

        source_posts_processed = 0

        # Drop accounts banned in this specific source or benched by a FloodWait
        # panic cooldown, then prefer those already joined.
        from app.core.safety_guidelines import account_in_flood_cooldown
        eligible = [
            a
            for a in accounts
            if source.id not in (a.banned_source_ids or [])
            and not account_in_flood_cooldown(a)
        ]
        if not eligible:
            logger.warning(
                "Task %s: all accounts banned in source %s, skipping", task.id, source.id
            )
            source_state.status = CommentSourceStateStatus.SKIPPED
            source_state.last_error = "all_accounts_banned_in_this_source"
            await db.commit()
            continue
        joined_first = sorted(
            eligible,
            key=lambda a: 0 if source.id in (a.joined_source_ids or []) else 1,
        )
        assigned_accounts = [joined_first[source_index % len(joined_first)]]

        for account in assigned_accounts:
            source_id = source.id
            source_state_id = source_state.id
            account_id = account.id
            source_state.status = CommentSourceStateStatus.IN_PROGRESS
            source_state.account_id = account_id
            source_state.attempts = (source_state.attempts or 0) + 1
            source_state.last_error = None
            await db.commit()

            if source_posts_processed >= task.comments_per_source:
                break

            # Progressive warmup cap: skip accounts that are too new or have
            # already reached their daily comment quota for this phase.
            age_days = effective_account_age_days(account)
            phase_max_comments = warmup_day_for(age_days).actions.get("comment", 0)
            if phase_max_comments == 0:
                logger.info(
                    "Task %s: account %s skipped — warmup_level=%s, phase blocks commenting",
                    task.id, account.id, getattr(account, "warmup_level", 0),
                )
                await log_action(db, task_id=task.id, action="account_too_new",
                                 account_id=account.id, source_id=source.id)
                continue
            if account_run_comments.get(account.id, 0) >= phase_max_comments:
                logger.info(
                    "Task %s: account %s reached warmup run cap (%s comments)",
                    task.id, account.id, phase_max_comments,
                )
                continue

            # NOTE: the warmup counter is incremented only when a comment is
            # ACTUALLY attempted (just before process_group_context/process_post
            # below), not here — otherwise a source the account could not even
            # access would burn a slot from the daily warmup quota.

            try:
                client = await asyncio.wait_for(telegram_service.get_client(account), timeout=45)
                access_status = await ensure_source_access(
                    db, task, source_state, source, account, client
                )
                if access_status != "ready":
                    source_posts_processed += 1
                    continue

                source_mode = effective_mode_for_source(task, source)
                if source_mode is None:
                    source_posts_processed += 1
                    source_state.status = CommentSourceStateStatus.SKIPPED
                    source_state.last_error = "source_type_not_selected_for_task"
                    await log_action(
                        db,
                        task_id=task.id,
                        action="skipped_source_type",
                        account_id=account.id,
                        source_id=source.id,
                        error_message=f"source_type={source.source_type}",
                    )
                    continue

                if source_mode == CommentTargetMode.GROUP_CONTEXT:
                    source_posts_processed += 1
                    account_run_comments[account.id] = account_run_comments.get(account.id, 0) + 1
                    result = await process_group_context(db, task, source, account, ai_client)
                    if result == "ok":
                        task.posts_checked += 1
                        source_state.status = CommentSourceStateStatus.DONE
                        source_state.last_processed_at = datetime.utcnow()
                    else:
                        source_state.status = CommentSourceStateStatus.SKIPPED
                        source_state.last_error = result
                else:
                    post = None
                    source_target = telegram_chat_target(source)
                    for message in await collect_recent_messages(client, source_target, limit=1):
                        if message.text or message.caption:
                            # Skip engagement-bait posts (asking for photos/shares without
                            # substantive content — AI would hallucinate about unseen images)
                            text = (message.text or message.caption or "").strip()
                            engagement_only = any(p in text.lower() for p in (
                                "присылайте фото", "присылайте фотографию", "поделитесь фото",
                                "присылайте свои фото", "присылайте работы",
                            )) and len(text) < 200
                            if not engagement_only:
                                post = message
                        break

                    if post:
                        source_posts_processed += 1
                        task.posts_checked += 1
                        account_run_comments[account.id] = account_run_comments.get(account.id, 0) + 1
                        result = await process_post(db, task, source, account, post, ai_client, source_mode)
                        if result == "ok":
                            source_state.status = CommentSourceStateStatus.DONE
                            source_state.last_processed_at = datetime.utcnow()
                        else:
                            source_state.status = CommentSourceStateStatus.SKIPPED
                            source_state.last_error = result
                        # Delay only after actual post processing (comment attempt),
                        # not when we simply skipped a source with no text.
                        delay = random.randint(task.min_delay, task.max_delay)
                        age_days = await _account_age_days(account)
                        phase = phase_for_age_days(age_days)
                        await asyncio.sleep(max(delay, phase.min_delay))
                    else:
                        source_state.status = CommentSourceStateStatus.SKIPPED
                        source_state.last_error = "latest_post_has_no_text"

            except Exception as e:
                error_str = str(e)
                logger.error(
                    "Error processing source %s with account %s: %s",
                    source_id,
                    account_id,
                    error_str,
                )
                await db.rollback()
                task_result = await db.execute(select(CommentTask).where(CommentTask.id == task.id))
                task = task_result.scalar_one()
                state_result = await db.execute(
                    select(CommentTaskSourceState).where(
                        CommentTaskSourceState.id == source_state_id
                    )
                )
                source_state = state_result.scalar_one()

                if "USER_BANNED_IN_CHANNEL" in error_str:
                    # Record the ban on the account so future runs skip this source.
                    acc_result = await db.execute(
                        select(Account).where(Account.id == account_id)
                    )
                    banned_acct = acc_result.scalar_one_or_none()
                    if banned_acct is not None:
                        from sqlalchemy.orm.attributes import flag_modified
                        ids: list = list(banned_acct.banned_source_ids or [])
                        if source_id not in ids:
                            ids.append(source_id)
                            banned_acct.banned_source_ids = ids
                            flag_modified(banned_acct, "banned_source_ids")
                    # Reset source to PENDING so a non-banned account can pick it up.
                    source_state.status = CommentSourceStateStatus.PENDING
                    source_state.account_id = None
                    source_state.last_error = f"account_{account_id}_banned_reset_for_retry"
                    await log_action(
                        db,
                        task_id=task.id,
                        action="account_banned_in_source",
                        account_id=account_id,
                        source_id=source_id,
                        error_message=error_str,
                    )
                else:
                    # If Telegram threw a large FloodWait, bench the account so
                    # the rest of the run (and other tasks) stop using it.
                    flood_secs = getattr(e, "value", None)
                    if flood_secs is not None:
                        from app.core.safety_guidelines import set_flood_cooldown
                        from sqlalchemy.orm.attributes import flag_modified
                        acc_result = await db.execute(
                            select(Account).where(Account.id == account_id)
                        )
                        flooded_acct = acc_result.scalar_one_or_none()
                        if flooded_acct is not None and set_flood_cooldown(flooded_acct, flood_secs):
                            flag_modified(flooded_acct, "health_factors")
                            logger.warning(
                                "Account %s benched by FloodWait panic cooldown (%ss)",
                                account_id, flood_secs,
                            )
                        # Return the source to the pool for another account.
                        source_state.status = CommentSourceStateStatus.PENDING
                        source_state.account_id = None
                    else:
                        source_state.status = CommentSourceStateStatus.FAILED
                    task.errors_count += 1
                    source_state.last_error = error_str[:500]
                    await log_action(
                        db,
                        task_id=task.id,
                        action="error",
                        account_id=account_id,
                        source_id=source_id,
                        error_message=error_str,
                    )

    await db.commit()


async def ensure_source_states(db: AsyncSession, task: CommentTask) -> None:
    """Create progress rows for newly added sources in a task."""
    source_ids = task.source_ids or []
    if not source_ids:
        return
    result = await db.execute(
        select(CommentTaskSourceState.source_id).where(
            CommentTaskSourceState.task_id == task.id,
            CommentTaskSourceState.source_id.in_(source_ids),
        )
    )
    existing = {row[0] for row in result.all()}
    for source_id in source_ids:
        if source_id not in existing:
            db.add(
                CommentTaskSourceState(
                    task_id=task.id,
                    source_id=source_id,
                    status=CommentSourceStateStatus.PENDING,
                )
            )
    await db.commit()


def effective_mode_for_source(task: CommentTask, source: TelegramSource) -> CommentTargetMode | None:
    modes = {mode.value if hasattr(mode, "value") else str(mode) for mode in (task.target_modes or [task.target_mode])}
    source_type = source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type)
    if source_type == "group" and CommentTargetMode.GROUP_CONTEXT.value in modes:
        return CommentTargetMode.GROUP_CONTEXT
    if source_type == "channel" and CommentTargetMode.CHANNEL_POSTS.value in modes:
        return CommentTargetMode.CHANNEL_POSTS
    return None


async def _is_member(client, target) -> bool:
    """Best-effort check whether the logged-in account can post in ``target``."""
    try:
        me = getattr(client, "me", None) or await client.get_me()
        member = await asyncio.wait_for(client.get_chat_member(target, me.id), timeout=20)
        status = str(getattr(member, "status", "")).lower()
        return not any(bad in status for bad in ("left", "banned", "restricted"))
    except Exception:  # noqa: BLE001
        return False


def _record_membership(account: Account, source_id: int) -> None:
    """Append source_id to account.joined_source_ids (idempotent, mutation-safe)."""
    from sqlalchemy.orm.attributes import flag_modified
    ids: list = list(account.joined_source_ids or [])
    if source_id not in ids:
        ids.append(source_id)
        account.joined_source_ids = ids
        flag_modified(account, "joined_source_ids")


async def _ensure_membership(db, task, source, account, client, source_target) -> None:
    """Join a public group/channel so the account can actually POST.

    Reading a public chat works without membership, but ``send_message``
    returns ``CHAT_WRITE_FORBIDDEN`` unless the account has joined. We
    check membership first (cheap) and only spend a rate-limited ``join``
    when the account is not already in. Idempotent and best-effort: a
    failure here is left for the post step to surface.
    """
    if await _is_member(client, source_target):
        return
    age_days = await _account_age_days(account)
    try:
        # join action max_delay_sec=600 — wrap with timeout so we never block
        # the event loop for 10 minutes without making progress.
        await asyncio.wait_for(
            rate_limiter.acquire("join", account.id, account_age_days=age_days),
            timeout=620,
        )
    except asyncio.TimeoutError:
        logger.warning("join rate_limiter timed out for account %s, proceeding", account.id)
    except (NewbornAccountError, RateLimitExceeded) as exc:
        logger.info("Skipping pre-post join for account %s: %s", account.id, exc)
        return
    try:
        await asyncio.wait_for(client.join_chat(source_target), timeout=45)
        await log_action(
            db, task_id=task.id, action="joined_source",
            account_id=account.id, source_id=source.id,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).upper()
        if "ALREADY" in msg or "PARTICIPANT" in msg:
            return
        logger.info("pre-post join for source %s returned: %s", source.id, exc)


async def ensure_source_access(
    db: AsyncSession,
    task: CommentTask,
    state: CommentTaskSourceState,
    source: TelegramSource,
    account: Account,
    client,
) -> str:
    """Ensure the selected account can access the source.

    For private invite links, this may send a join request. That is
    recorded as JOIN_REQUESTED so the task can retry later after a
    human/admin approves the request. This path is intended only for
    sources where the operator has permission to join.
    """
    try:
        source_target = telegram_chat_target(source)
        chat = await asyncio.wait_for(client.get_chat(source_target), timeout=30)
        detected_type = _source_type_from_chat(chat)
        if detected_type and source.source_type != detected_type:
            source.source_type = detected_type
            await db.commit()
        # Reading a public group/channel works WITHOUT membership, but
        # posting a comment does not — Telegram returns
        # ``CHAT_WRITE_FORBIDDEN`` unless the account has joined. Join now
        # (rate-limited, like a real user would) so the comment can be
        # published. Already-a-member is a harmless no-op.
        await _ensure_membership(db, task, source, account, client, source_target)
        _record_membership(account, source.id)
        await db.commit()
        return "ready"
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc)

    invite_link = "/+" in source.normalized_link or "/joinchat/" in source.normalized_link
    if not invite_link:
        state.status = CommentSourceStateStatus.FAILED
        state.last_error = error_text[:500]
        await log_action(
            db,
            task_id=task.id,
            action="source_access_error",
            account_id=account.id,
            source_id=source.id,
            error_message=error_text[:500],
        )
        await db.commit()
        return "failed"

    age_days = await _account_age_days(account)
    try:
        await rate_limiter.acquire("join", account.id, account_age_days=age_days)
        source_target = telegram_chat_target(source)
        await asyncio.wait_for(client.join_chat(source_target), timeout=45)
        try:
            chat = await asyncio.wait_for(client.get_chat(source_target), timeout=30)
            detected_type = _source_type_from_chat(chat)
            if detected_type and source.source_type != detected_type:
                source.source_type = detected_type
        except Exception:
            pass
        await log_action(
            db,
            task_id=task.id,
            action="joined_source",
            account_id=account.id,
            source_id=source.id,
        )
        return "ready"
    except Exception as exc:  # noqa: BLE001
        join_error = str(exc)
        if "INVITE_REQUEST_SENT" in join_error or "request" in join_error.lower():
            state.status = CommentSourceStateStatus.JOIN_REQUESTED
            state.last_error = "join_request_sent_waiting_for_approval"
            await log_action(
                db,
                task_id=task.id,
                action="join_request_sent",
                account_id=account.id,
                source_id=source.id,
            )
            await db.commit()
            return "join_requested"
        state.status = CommentSourceStateStatus.FAILED
        state.last_error = join_error[:500]
        await log_action(
            db,
            task_id=task.id,
            action="join_error",
            account_id=account.id,
            source_id=source.id,
            error_message=join_error[:500],
        )
        await db.commit()
        return "failed"


def _source_type_from_chat(chat) -> TelegramSourceType | None:
    chat_type = getattr(chat, "type", None)
    if chat_type == ChatType.CHANNEL:
        return TelegramSourceType.CHANNEL
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return TelegramSourceType.GROUP
    if chat_type in (ChatType.PRIVATE, ChatType.BOT):
        return TelegramSourceType.CHAT
    return None


async def process_group_context(
    db: AsyncSession,
    task: CommentTask,
    source: TelegramSource,
    account: Account,
    ai_client,
) -> str:
    """Create a draft message for a group based on the last 5 messages."""
    client = await asyncio.wait_for(telegram_service.get_client(account), timeout=45)
    messages: list[str] = []
    source_target = telegram_chat_target(source)
    # Pull a wider window (newest-first) and keep only the last 5 GENUINE
    # human comments. A naive "last 5 messages" picked up service notices
    # and ads, which is exactly what poisoned the AI replies before.
    for message in await collect_recent_messages(client, source_target, limit=60):
        if _is_human_comment(message):
            messages.append((message.text or message.caption or "").strip())
        if len(messages) >= 5:
            break

    if not messages:
        await log_action(
            db,
            task_id=task.id,
            action="skipped_no_group_messages",
            account_id=account.id,
            source_id=source.id,
        )
        return "no_recent_group_messages"

    context_text = "RECENT GROUP MESSAGES:\n" + "\n".join(
        f"- {message}" for message in reversed(messages)
    )
    draft_text = await generate_comment_draft(
        ai_client,
        context_text,
        task.topic,
        task.model,
        target_mode=CommentTargetMode.GROUP_CONTEXT,
    )
    if not draft_text:
        await log_action(
            db,
            task_id=task.id,
            action="skipped_ai_generation_failed",
            account_id=account.id,
            source_id=source.id,
        )
        return "ai_generation_failed"

    draft = CommentDraft(
        task_id=task.id,
        source_id=source.id,
        account_id=account.id,
        post_id=0,
        post_text=context_text,
        draft_text=draft_text,
        moderation_flagged=False,
        moderation_reason=None,
        status="pending" if task.policy != CommentPolicy.AUTO_PUBLISH else "approved",
        approved_by="auto" if task.policy == CommentPolicy.AUTO_PUBLISH else None,
        approved_at=datetime.utcnow() if task.policy == CommentPolicy.AUTO_PUBLISH else None,
    )
    db.add(draft)
    task.drafts_created += 1
    await log_action(
        db,
        task_id=task.id,
        action="created_group_draft",
        account_id=account.id,
        source_id=source.id,
    )

    if task.policy == CommentPolicy.AUTO_PUBLISH:
        # Join first (idempotent, no-op if already member). Must happen before
        # the rate-limit token so we don't burn a slot then fail on CHAT_WRITE_FORBIDDEN.
        await _ensure_membership(db, task, source, account, client, source_target)
        if not await _safe_acquire_comment_token(account, db, task.id):
            draft.error_message = (
                "Не опубликовано: аккаунт слишком молодой или достигнут дневной лимит."
            )
            await db.commit()
            return "rate_limit_or_newborn"
        try:
            sent = await asyncio.wait_for(client.send_message(source_target, draft_text), timeout=45)
        except Exception as e:
            # Record the send error on the draft before re-raising so the draft
            # doesn't stay stuck as "approved" with no explanation.
            draft.error_message = str(e)
            await db.commit()
            raise
        draft.status = "published"
        draft.published_message_id = sent.id
        draft.published_at = datetime.utcnow()
        task.comments_posted += 1
        await log_action(
            db,
            task_id=task.id,
            action="published",
            account_id=account.id,
            source_id=source.id,
            draft_id=draft.id,
            details={"mode": "group_context", "message_id": sent.id},
        )

    return "ok"


async def process_post(
    db: AsyncSession,
    task: CommentTask,
    source: TelegramSource,
    account: Account,
    post,
    ai_client,
    target_mode: CommentTargetMode | None = None,
) -> str:
    """Read context, generate a draft, save it, optionally publish."""
    post_text = post.text or post.caption or ""

    client = await asyncio.wait_for(telegram_service.get_client(account), timeout=45)
    source_target = telegram_chat_target(source)

    # Try to get discussion replies for context. ``get_discussion_message``
    # and ``get_discussion_replies`` are heavy on Telegram's side,
    # so we acquire a second ``comment`` token for them — otherwise
    # a comment run could read 100+ discussion threads in seconds
    # and trip FloodWait.
    age_days = await _account_age_days(account)
    try:
        # comment max_delay_sec=180 — wrap with timeout so event loop never blocks.
        await asyncio.wait_for(
            rate_limiter.acquire("comment", account.id, account_age_days=age_days),
            timeout=220,
        )
    except asyncio.TimeoutError:
        logger.warning("discussion-read rate_limiter timed out for account %s, proceeding", account.id)
    except SkipAction:
        # Humanization: skip this post entirely (account "scrolled past" it).
        await log_action(
            db,
            task_id=task.id,
            action="skipped_humanization",
            account_id=account.id,
            source_id=source.id,
        )
        return "humanization_skip"
    except (NewbornAccountError, RateLimitExceeded) as exc:
        logger.info("Skipping discussion read for %s: %s", account.id, exc)
        await log_action(
            db,
            task_id=task.id,
            action="skipped_rate_limit",
            account_id=account.id,
            source_id=source.id,
            error_message=str(exc),
        )
        return "rate_limit_or_newborn"

    context_messages: list[str] = []
    try:
        discussion = await asyncio.wait_for(
            client.get_discussion_message(source_target, post.id),
            timeout=45,
        )
        if discussion:
            try:
                # Pull a wider window and keep only real human replies
                # (filters service notices, channel auto-posts, bots, ads).
                for reply in await collect_discussion_replies(client, source_target, post.id, limit=60):
                    if _is_human_comment(reply):
                        context_messages.append((reply.text or reply.caption or "").strip())
                    if len(context_messages) >= 5:
                        break
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        # Post might not have discussion enabled.
        pass

    context_text = f"POST: {post_text}"
    if context_messages:
        context_text += "\n\nRECENT REPLIES:\n" + "\n".join(
            f"- {msg}" for msg in context_messages
        )

    draft_text = await generate_comment_draft(
        ai_client,
        context_text,
        task.topic,
        task.model,
        target_mode=target_mode or task.target_mode,
    )
    if not draft_text:
        await log_action(
            db,
            task_id=task.id,
            action="skipped_ai_generation_failed",
            account_id=account.id,
            source_id=source.id,
        )
        return "ai_generation_failed"

    # Simple moderation check (flag suspicious content).
    moderation_flagged = False
    moderation_reason = None
    if task.moderation_enabled:
        forbidden_words = [
            "https://",
            "bit.ly",
            "t.me/+",
            "заработ",
        ]
        for word in forbidden_words:
            if word.lower() in draft_text.lower():
                moderation_flagged = True
                moderation_reason = (
                    f"draft contains forbidden token: {word}"
                )
                break

    if task.policy == CommentPolicy.AUTO_PUBLISH and not moderation_flagged:
        status = "approved"
        approved_by = "auto"
    else:
        status = "pending" if not moderation_flagged else "rejected"
        approved_by = "auto" if moderation_flagged else None

    draft = CommentDraft(
        task_id=task.id,
        source_id=source.id,
        account_id=account.id,
        post_id=post.id,
        post_text=post_text,
        draft_text=draft_text,
        moderation_flagged=moderation_flagged,
        moderation_reason=moderation_reason,
        status=status,
        approved_by=approved_by,
        approved_at=datetime.utcnow() if approved_by else None,
    )
    db.add(draft)
    task.drafts_created += 1
    # Flush so the autoincrement PK is assigned before we log it — otherwise
    # ``draft.id`` is still None and the log records draft_id=null.
    await db.flush()

    await log_action(
        db,
        task_id=task.id,
        action="created_draft",
        account_id=account.id,
        source_id=source.id,
        details={"draft_id": draft.id, "status": status},
    )

    if status == "approved":
        await publish_draft(db, task, draft)
        if draft.status != "published":
            return draft.error_message or "publish_failed"

    return "ok"


async def generate_comment_draft(
    ai_client,
    context_text: str,
    topic: str,
    model: str,
    target_mode: CommentTargetMode = CommentTargetMode.CHANNEL_POSTS,
) -> str | None:
    """Generate a short AI comment draft via the configured provider."""
    try:
        # Natural, human-sounding Russian. Core discipline:
        # 1. No generic AI praise ("Отлично!").
        # 2. Never claim to have contacts, to have messaged anyone, or to know
        #    specific people/addresses — those are hallucinations and mislead real users.
        # 3. Never act as an admin.
        # 4. Never pose as a customer looking for services.
        hard_bans = (
            "НЕЛЬЗЯ: рекомендовать конкретных людей по имени, называть конкретные адреса "
            "или районы, говорить что 'писал/писала в лс', представляться клиентом ищущим услугу, "
            "выступать как администратор ('не флудите', 'читайте правила'), "
            "делать вид что владеешь инсайдерской информацией. "
        )
        base_rules = (
            "Пиши только на русском. "
            "Одна-две короткие фразы, как живой человек пишет в Telegram. "
            "Запрещены: эмодзи, восклицательные знаки, 'Отлично!', 'Супер!', "
            "'Класс!', 'Красиво!', 'Здорово!', приветствия, прощания, реклама, ссылки. "
            "МОЖНО: задать общий вопрос по теме разговора, высказать короткое наблюдение. "
            "Не раскрывай, что ты ИИ. Максимум 20 слов. "
        ) + hard_bans
        if target_mode == CommentTargetMode.GROUP_CONTEXT:
            system_prompt = (
                "Ты читатель Telegram-группы. Напиши одно нейтральное короткое сообщение "
                "по теме текущего разговора — задай общий вопрос по обсуждаемой теме "
                "или выскажи нейтральное наблюдение. " + base_rules
            )
        else:
            system_prompt = (
                "Ты читатель Telegram-канала. Напиши короткий комментарий "
                "к этому конкретному посту — по его содержанию, не общий. " + base_rules
            )
        if topic:
            system_prompt += f" Тематика: {topic}."

        request_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"CONTEXT: {context_text}\n\nREPLY:",
                },
            ],
            "max_tokens": 120,
            "temperature": 0.9,
        }
        if str(model).startswith("deepseek-v4"):
            # V4 defaults to thinking mode. For short Telegram comments we need
            # a direct final answer, otherwise the small max_tokens budget can
            # be spent on reasoning and return an empty content field.
            request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        response = await asyncio.wait_for(
            ai_client.chat.completions.create(**request_kwargs),
            timeout=30,
        )

        content = response.choices[0].message.content or ""
        draft_text = content.strip()
        return draft_text.strip('"').strip("'") or None
    except asyncio.TimeoutError:
        logger.error("AI generation timed out after 30s")
        return None
    except Exception as e:  # noqa: BLE001
        logger.error("AI generation error: %s", e)
        return None


async def publish_draft(
    db: AsyncSession, task: CommentTask, draft: CommentDraft
) -> None:
    """Publish an approved draft to the channel's discussion group.

    The Telegram call is gated by the rate limiter (per
    ``app.core.safety_guidelines.comment``) — see module docstring.
    """
    try:
        account_result = await db.execute(
            select(Account)
            .options(selectinload(Account.proxy))
            .where(Account.id == draft.account_id)
        )
        account = account_result.scalar_one_or_none()
        source_result = await db.execute(
            select(TelegramSource).where(TelegramSource.id == draft.source_id)
        )
        source = source_result.scalar_one_or_none()

        if not account or not source:
            return

        # Acquire a token before posting. Newborn accounts
        # are skipped with a log; daily caps are respected. We now record
        # WHY on the draft so a manual "approve" that can't publish doesn't
        # look like nothing happened.
        if not await _safe_acquire_comment_token(account, db, task.id):
            draft.error_message = (
                "Не опубликовано: аккаунт слишком молодой для комментариев "
                "или достигнут дневной лимит. Дайте аккаунту прогреться или "
                "повторите завтра."
            )
            task.errors_count += 1
            await db.commit()
            return

        client = await asyncio.wait_for(telegram_service.get_client(account), timeout=45)
        source_target = telegram_chat_target(source)

        source_type = source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type)
        if source_type == "group" or draft.post_id == 0:
            sent = await asyncio.wait_for(client.send_message(source_target, draft.draft_text), timeout=45)
            draft.status = "published"
            draft.published_message_id = sent.id
            draft.published_at = datetime.utcnow()
            task.comments_posted += 1
            await log_action(
                db,
                task_id=task.id,
                action="published",
                account_id=account.id,
                source_id=source.id,
                details={"draft_id": draft.id, "mode": "group_context"},
            )
            return

        try:
            discussion = await asyncio.wait_for(
                client.get_discussion_message(source_target, draft.post_id),
                timeout=45,
            )
            if discussion:
                target_chat_id = getattr(getattr(discussion, "chat", None), "id", None)
                target_chat_id = target_chat_id or source.normalized_link
                sent = await asyncio.wait_for(
                    client.send_message(
                        target_chat_id,
                        draft.draft_text,
                        reply_to_message_id=discussion.id,
                    ),
                    timeout=45,
                )
                draft.status = "published"
                draft.published_message_id = sent.id
                draft.published_at = datetime.utcnow()
                task.comments_posted += 1
                await log_action(
                    db,
                    task_id=task.id,
                    action="published",
                    account_id=account.id,
                    source_id=source.id,
                    details={"draft_id": draft.id},
                )
        except Exception as e:  # noqa: BLE001
            draft.error_message = str(e)
            task.errors_count += 1
            await log_action(
                db,
                task_id=task.id,
                action="publish_error",
                details={"draft_id": draft.id},
                error_message=str(e),
            )
    except Exception as e:  # noqa: BLE001
        logger.error("Publish error: %s", e)


async def log_action(
    db: AsyncSession,
    *,
    task_id: int | None = None,
    action: str,
    account_id: int | None = None,
    source_id: int | None = None,
    draft_id: int | None = None,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Persist a single ``CommentLog`` row."""
    log = CommentLog(
        task_id=task_id,
        action=action,
        account_id=account_id,
        source_id=source_id,
        draft_id=draft_id,
        details=details,
        error_message=error_message,
    )
    db.add(log)
    await db.commit()


# ---------------------------------------------------------------------------
# Admin controls
# ---------------------------------------------------------------------------
@celery_app.task(name="app.tasks.commenting.pause_comment_task")
def pause_comment_task(task_id: int):
    return async_run(_set_status(task_id, CommentTaskStatus.PAUSED))


@celery_app.task(name="app.tasks.commenting.stop_comment_task")
def stop_comment_task(task_id: int):
    async def _run():
        async with SessionLocal() as db:
            result = await db.execute(
                select(CommentTask).where(CommentTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task:
                task.status = CommentTaskStatus.STOPPED
                task.finished_at = datetime.utcnow()
                await db.commit()

    return async_run(_run())


@celery_app.task(name="app.tasks.commenting.approve_draft")
def approve_draft(draft_id: int, approved_by: str = "manual"):
    return async_run(_approve_draft(draft_id, approved_by))


async def _set_status(task_id: int, status) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(CommentTask).where(CommentTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.status = status
            await db.commit()


async def _approve_draft(draft_id: int, approved_by: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(CommentDraft).where(CommentDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()
        # The HTTP endpoint flips the row to "approved" and commits BEFORE
        # dispatching this task, so guarding on ``== "pending"`` made the
        # whole approve click a silent no-op (the user's bug: "нажал
        # подтвердить — ничего не произошло"). Accept both states.
        if draft and draft.status in ("pending", "approved"):
            draft.status = "approved"
            draft.approved_by = approved_by
            draft.approved_at = datetime.utcnow()
            await db.commit()

            task_result = await db.execute(
                select(CommentTask).where(CommentTask.id == draft.task_id)
            )
            task = task_result.scalar_one_or_none()
            if task:
                await publish_draft(db, task, draft)


@celery_app.task(name="app.tasks.commenting.reject_draft")
def reject_draft(draft_id: int, reason: str = None):
    return async_run(_reject_draft(draft_id, reason))


async def _reject_draft(draft_id: int, reason: str | None) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(CommentDraft).where(CommentDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()
        if draft and draft.status == "pending":
            draft.status = "rejected"
            draft.rejection_reason = reason
            draft.approved_at = datetime.utcnow()
            await db.commit()

            await log_action(
                db,
                task_id=draft.task_id,
                action="rejected",
                details={"reason": reason, "draft_id": draft_id},
            )
