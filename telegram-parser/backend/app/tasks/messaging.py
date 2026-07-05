"""
Bulk Messaging Service
Массовая рассылка сообщений с rate limiting и flood wait handling

Based on:
- mehdi-jahani/telegram_message_sender (Excel input, 7-day duplicate prevention)
  https://github.com/mehdi-jahani/telegram_message_sender
- VoxHash/Telegram-Multi-Account-Message-Sender (round-robin, spintax)
  https://github.com/VoxHash/Telegram-Multi-Account-Message-Sender
- ItsOrv/Telegram-Panel (bulk operations with semaphore, flood wait)
  https://github.com/ItsOrv/Telegram-Panel

Key patterns:
- Round-robin account selection
- FloodWaitError automatic handling
- Per-campaign recipient tracking via ``CampaignRecipient``
  (replaces the broken global ``Contact.is_processed`` flag, so the
  same contact can be re-targeted in a follow-up campaign)
- Async semaphore for concurrency control
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, List, Tuple

from pyrogram.errors import FloodWait
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import async_run, celery_app
from app.core.rate_limiter import rate_limiter, RateLimitExceeded, NewbornAccountError, SkipAction
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.campaign import Campaign, CampaignStatus, MessageLog as MessageLogModel
from app.models.campaign_recipient import CampaignRecipient, RecipientStatus
from app.models.contact import Contact
from app.services.telegram_service import telegram_service
from app.services.template_service import get_randomized_content

logger = logging.getLogger(__name__)

# Constants from Telegram-Panel
MAX_CONCURRENT_OPERATIONS = 5
DEFAULT_DELAY_MIN = 2.0
DEFAULT_DELAY_MAX = 5.0

# How many recipients to load per run_campaign invocation. We keep
# this modest so a single tick doesn't lock the worker for hours, and
# a stuck row doesn't sit forever.
BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_session_revoked_error(error: Exception) -> bool:
    """Check if error indicates session revocation."""
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()
    return any(
        keyword in error_msg
        for keyword in [
            "session",
            "revoked",
            "not logged in",
            "auth key",
            "authorization",
            "key is not registered",
            "unregistered",
            "invalidated",
        ]
    ) or any(keyword in error_type for keyword in ["revoked", "auth", "unregistered"])


async def execute_bulk_operation(
    accounts: List[Account],
    operation_func: Callable[[Account], Awaitable[Any]],
    operation_name: str,
    semaphore: asyncio.Semaphore,
    counter_lock: asyncio.Lock,
    delay_range: Tuple[float, float] = (DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX),
) -> Tuple[int, int, List[str]]:
    """Execute bulk operation across multiple accounts."""
    success_count = 0
    error_count = 0
    revoked_sessions: List[str] = []

    async def execute_with_account(account: Account) -> None:
        nonlocal success_count, error_count, revoked_sessions
        async with semaphore:
            try:
                await operation_func(account)
                async with counter_lock:
                    success_count += 1
                await asyncio.sleep(random.uniform(*delay_range))
            except FloodWait as e:
                async with counter_lock:
                    error_count += 1
                logger.warning(
                    "FloodWaitError for account %s: waiting %ss",
                    account.id,
                    e.value,
                )
                await asyncio.sleep(e.value)
            except Exception as e:
                if is_session_revoked_error(e):
                    async with counter_lock:
                        error_count += 1
                        revoked_sessions.append(str(account.id))
                    logger.warning("Session revoked for account %s: %s", account.id, e)
                else:
                    async with counter_lock:
                        error_count += 1
                    logger.error(
                        "Error in %s with account %s: %s",
                        operation_name,
                        account.id,
                        e,
                    )

    await asyncio.gather(
        *(execute_with_account(acc) for acc in accounts), return_exceptions=True
    )

    return success_count, error_count, revoked_sessions


async def send_single_message(
    account: Account,
    target: str,
    message: str,
    delay: int = 2,
) -> Tuple[bool, str | None]:
    """Send a single message using an account.

    Returns (success, error_message). Goes through the shared
    :class:`RateLimiter` first so campaigns, warmup, reactions, and
    group-join can't all hammer the same account in the same second.

    The limiter consults :mod:`app.core.safety_guidelines` to pick
    a phase-appropriate delay envelope and daily cap based on
    ``account.created_at``. Newborn accounts (0-3 days) raise
    :class:`NewbornAccountError` — we surface that to the recipient
    as a normal SKIP rather than burning a FloodWait on an account
    that isn't ready.
    """
    from app.core.safety_guidelines import effective_account_age_days
    account_age_days = effective_account_age_days(account)
    try:
        await rate_limiter.acquire(
            "send", account.id, account_age_days=account_age_days, min_delay=delay
        )
    except SkipAction:
        # "send" never opts into humanization skips today, but handle it
        # defensively so a future probability change can't surface as an error.
        logger.info("Humanization skip for send on account %s", account.id)
        return False, "humanization_skip"
    except NewbornAccountError as exc:
        logger.warning("Skipping send for newborn account: %s", exc)
        return False, f"newborn_account: {exc.phase}"
    except RateLimitExceeded as exc:
        logger.warning("RateLimit hit: %s", exc)
        return False, f"daily_limit: phase={exc.phase} limit={exc.limit}"

    try:
        client = await telegram_service.get_client(account)
        await client.send_chat_action(target, "typing")
        await asyncio.sleep(random.randint(2, 5))
        await client.send_message(target, message)
        await asyncio.sleep(delay)
        return True, None
    except FloodWait as e:
        # Honour Telegram's FloodWait exactly. The recommended
        # pattern (grammy.dev/advanced/flood) is "wait and retry"
        # — we sleep and re-raise so the caller can decide whether
        # to retry or to mark the recipient as FAILED_RETRY.
        logger.warning("FloodWait for account %s: %ss", account.id, e.value)
        await asyncio.sleep(e.value)
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(
            "Failed to send message from %s to %s: %s", account.id, target, error_msg
        )
        return False, error_msg


# ---------------------------------------------------------------------------
# Campaign recipient helpers
# ---------------------------------------------------------------------------
async def ensure_recipients(
    db, campaign_id: int, project_id: int
) -> int:
    """Create CampaignRecipient rows for every contact in the project
    that doesn't already have one. Returns the number of rows created.

    Idempotent — re-running on the same campaign is a no-op.
    """
    # Recipients that already exist.
    existing = await db.execute(
        select(CampaignRecipient.contact_id).where(
            CampaignRecipient.campaign_id == campaign_id
        )
    )
    already = {row[0] for row in existing.fetchall()}

    # All contacts in the project.
    all_contacts = await db.execute(
        select(Contact.id).where(Contact.project_id == project_id)
    )
    target_ids = [row[0] for row in all_contacts.fetchall() if row[0] not in already]

    if not target_ids:
        return 0

    db.add_all(
        CampaignRecipient(
            campaign_id=campaign_id,
            contact_id=cid,
            status=RecipientStatus.PENDING,
        )
        for cid in target_ids
    )
    try:
        await db.commit()
    except IntegrityError:
        # Race condition with another worker creating the same row;
        # safe to ignore because the goal is "row exists".
        await db.rollback()
    return len(target_ids)


async def _claim_recipient(
    db, recipient_id: int, account_id: int
) -> bool:
    """Mark a recipient as SENDING. Returns True if we got the lock.

    Other workers checking the same row will see status=SENDING and
    skip it. We rely on the row's primary key for the implicit lock
    plus the ``WHERE status = 'PENDING'`` guard.
    """
    res = await db.execute(
        select(CampaignRecipient)
        .where(CampaignRecipient.id == recipient_id)
        .where(
            CampaignRecipient.status.in_(
                [RecipientStatus.PENDING, RecipientStatus.FAILED_RETRY]
            )
        )
    )
    recipient = res.scalar_one_or_none()
    if not recipient:
        return False
    recipient.status = RecipientStatus.SENDING
    recipient.account_id = account_id
    recipient.attempts += 1
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@celery_app.task(name="app.tasks.messaging.run_campaign")
def run_campaign(campaign_id: int):
    """Run a single batch of a campaign.

    Behaviour
    ---------
    1. Lazily create ``CampaignRecipient`` rows for every contact in
       the project (idempotent).
    2. Pull up to ``BATCH_SIZE`` PENDING / FAILED_RETRY recipients.
    3. For each one: claim, send, mark SENT/FAILED, write a
       ``MessageLog`` row.
    4. If the daily cap was hit, re-queue with a 1-hour countdown.
       Otherwise re-queue with a 1-second countdown so the next batch
       starts immediately.
    5. If every recipient is SENT/FAILED/SKIPPED, mark the campaign
       COMPLETED.
    """
    return async_run(_run_campaign(campaign_id))


async def _run_campaign(campaign_id: int) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Campaign)
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.template))
        )
        campaign = result.scalar_one_or_none()

        if not campaign:
            logger.error("Campaign %s not found", campaign_id)
            return

        if campaign.status != CampaignStatus.RUNNING:
            logger.info("Campaign %s is not in RUNNING state", campaign_id)
            return

        # 1. Make sure every project contact has a recipient row.
        await ensure_recipients(db, campaign_id, campaign.project_id)

        # 2. Pull a batch of PENDING / FAILED_RETRY recipients.
        recipients_result = await db.execute(
            select(CampaignRecipient)
            .where(CampaignRecipient.campaign_id == campaign_id)
            .where(
                CampaignRecipient.status.in_(
                    [RecipientStatus.PENDING, RecipientStatus.FAILED_RETRY]
                )
            )
            .order_by(CampaignRecipient.id)
            .limit(BATCH_SIZE)
        )
        recipients = list(recipients_result.scalars().all())

        if not recipients:
            # Anything left to do?
            pending_anywhere = await db.execute(
                select(func.count(CampaignRecipient.id)).where(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status.in_(
                        [RecipientStatus.PENDING, RecipientStatus.FAILED_RETRY]
                    ),
                )
            )
            if (pending_anywhere.scalar() or 0) == 0:
                campaign.status = CampaignStatus.COMPLETED
                await db.commit()
            else:
                # Should not happen — defensive re-queue.
                run_campaign.apply_async(args=[campaign_id], countdown=60)
            return

        # 3. Available accounts (round-robin pool).
        accounts_result = await db.execute(
            select(Account).where(
                Account.status == "production",
                Account.project_id == campaign.project_id,
            )
        )
        accounts = list(accounts_result.scalars().all())
        if not accounts:
            logger.error("No production accounts available")
            campaign.status = CampaignStatus.FAILED
            await db.commit()
            return

        # Filter out newborn accounts (0-3 days) before doing any
        # work. Trying to send from a newborn account wastes a
        # token in the rate limiter and triggers a FloodWait on
        # an account that isn't even allowed to DM yet.
        from app.core.safety_guidelines import (
            phase_for_age_days,
            effective_account_age_days,
            account_in_flood_cooldown,
        )

        eligible_accounts = []
        for acc in accounts:
            # Skip accounts benched by a FloodWait panic cooldown — Telegram
            # already flagged them; continuing to send risks a ban.
            if account_in_flood_cooldown(acc):
                logger.info(
                    "Skipping account %s in campaign %s — FloodWait cooldown active",
                    acc.id,
                    campaign_id,
                )
                continue
            age = effective_account_age_days(acc)
            phase = phase_for_age_days(age)
            if phase.multiplier > 0:
                eligible_accounts.append(acc)
            else:
                logger.info(
                    "Skipping newborn account %s in campaign %s (phase=%s)",
                    acc.id,
                    campaign_id,
                    phase.name,
                )
        if not eligible_accounts:
            logger.warning(
                "All accounts are newborn; campaign %s cannot run yet",
                campaign_id,
            )
            # Don't mark the campaign as FAILED — the operator
            # probably wants to retry once the accounts age. Just
            # re-queue for tomorrow.
            run_campaign.apply_async(args=[campaign_id], countdown=86400)
            return
        accounts = eligible_accounts

        # 4. Daily cap from the rolling 24h window.
        sent_today_result = await db.execute(
            select(func.count(MessageLogModel.id)).where(
                MessageLogModel.campaign_id == campaign_id,
                MessageLogModel.status == "sent",
                MessageLogModel.sent_at >= datetime.utcnow() - timedelta(days=1),
            )
        )
        sent_today = sent_today_result.scalar() or 0
        max_per_day = campaign.max_per_day or 100
        daily_limit_reached = False
        flood_wait_hit = False

        for i, recipient in enumerate(recipients):
            # Daily cap.
            if sent_today >= max_per_day:
                logger.info("Daily message limit reached: %s", max_per_day)
                daily_limit_reached = True
                break

            # Honour pause / stop requests.
            await db.refresh(campaign)
            if campaign.status != CampaignStatus.RUNNING:
                logger.info("Campaign %s was stopped/paused", campaign_id)
                break

            # Try to claim the recipient (another worker might have
            # taken it since we loaded the batch).
            account = accounts[i % len(accounts)]
            if not await _claim_recipient(db, recipient.id, account.id):
                continue

            # Load the contact (we need its fields for templating).
            contact = await db.get(Contact, recipient.contact_id)
            if not contact:
                recipient.status = RecipientStatus.SKIPPED
                recipient.last_error = "contact not found"
                await db.commit()
                continue

            target = contact.username or contact.phone_number
            if not target:
                recipient.status = RecipientStatus.SKIPPED
                recipient.last_error = "no username/phone"
                db.add(
                    MessageLogModel(
                        campaign_id=campaign.id,
                        account_id=account.id,
                        contact_id=contact.id,
                        status="failed",
                        error_message="Contact has no username or phone number",
                    )
                )
                await db.commit()
                continue

            variables = {
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "username": contact.username or "",
            }
            text = (
                get_randomized_content(campaign.template, variables)
                if campaign.template
                else "Hello"
            )

            logger.info("Sending from account %s to %s", account.id, target)
            try:
                success, error_msg = await send_single_message(
                    account,
                    target,
                    text,
                    # ``sorted`` guards against a misconfigured campaign
                    # where min_delay > max_delay (randint would raise).
                    delay=random.randint(*sorted((campaign.min_delay, campaign.max_delay))),
                )
            except FloodWait as e:
                # ``send_single_message`` already slept ``e.value`` before
                # re-raising. Without this guard the exception would bubble
                # out of the whole run, leaving the claimed recipient stuck
                # in SENDING forever (never re-selected) and the campaign
                # frozen in RUNNING (no re-queue). Instead: return the
                # recipient to the retry pool and stop this batch cleanly.
                logger.warning(
                    "FloodWait %ss aborting campaign %s batch", e.value, campaign_id
                )
                # A large FloodWait means Telegram flagged this account as spammy.
                # Bench it (panic cooldown) so the next batch skips it instead of
                # continuing to send and risking a ban.
                from app.core.safety_guidelines import set_flood_cooldown
                from sqlalchemy.orm.attributes import flag_modified
                if set_flood_cooldown(account, e.value):
                    flag_modified(account, "health_factors")
                    logger.warning(
                        "Account %s benched by FloodWait panic cooldown (%ss)",
                        account.id, e.value,
                    )
                recipient.status = RecipientStatus.FAILED_RETRY
                recipient.last_error = f"flood_wait:{e.value}"[:500]
                db.add(
                    MessageLogModel(
                        campaign_id=campaign.id,
                        account_id=account.id,
                        contact_id=contact.id,
                        status="failed",
                        error_message=f"FloodWait {e.value}s",
                    )
                )
                await db.commit()
                flood_wait_hit = True
                break

            # Persist MessageLog (kept for historical stats).
            db.add(
                MessageLogModel(
                    campaign_id=campaign.id,
                    account_id=account.id,
                    contact_id=contact.id,
                    status="sent" if success else "failed",
                    error_message=error_msg,
                )
            )

            if success:
                recipient.status = RecipientStatus.SENT
                recipient.sent_at = datetime.utcnow()
                sent_today += 1
            else:
                # Leave room for a future retry; ``next_retry_at`` is
                # set by the rate limiter / FloodWait handler if
                # appropriate.
                recipient.status = RecipientStatus.FAILED
                recipient.last_error = (error_msg or "")[:500]
            await db.commit()

        # 5. Decide what's next.
        pending_result = await db.execute(
            select(func.count(CampaignRecipient.id)).where(
                CampaignRecipient.campaign_id == campaign_id,
                CampaignRecipient.status.in_(
                    [RecipientStatus.PENDING, RecipientStatus.FAILED_RETRY]
                ),
            )
        )
        pending_remaining = pending_result.scalar() or 0

        if pending_remaining == 0:
            campaign.status = CampaignStatus.COMPLETED
            await db.commit()
        else:
            # Daily cap: wait an hour so we don't tight-loop into a ban.
            # FloodWait: back off a minute before the next batch (we already
            # slept the server-mandated interval inside send_single_message).
            if daily_limit_reached:
                countdown = 3600
            elif flood_wait_hit:
                countdown = 60
            else:
                countdown = 1
            run_campaign.apply_async(args=[campaign_id], countdown=countdown)


@celery_app.task(name="app.tasks.messaging.send_to_single")
def send_to_single(contact_id: int, campaign_id: int):
    """Send a single message to one contact. Used by ad-hoc flows
    (reactions, chatting) that don't run a full campaign.
    """
    return async_run(_send_to_single(contact_id, campaign_id))


async def _send_to_single(contact_id: int, campaign_id: int) -> None:
    async with SessionLocal() as db:
        contact = await db.get(Contact, contact_id)
        campaign = await db.get(Campaign, campaign_id)

        if not contact or not campaign:
            return

        accounts = await db.execute(
            select(Account).where(
                Account.status == "production",
                Account.project_id == campaign.project_id,
            )
        )
        accounts = list(accounts.scalars().all())

        if not accounts:
            return

        account = accounts[0]
        target = contact.username or contact.phone_number
        if not target:
            return

        variables = {
            "first_name": contact.first_name or "",
            "last_name": contact.last_name or "",
            "username": contact.username or "",
        }
        text = (
            get_randomized_content(campaign.template, variables)
            if campaign.template
            else "Hello"
        )

        success, error = await send_single_message(account, target, text)

        db.add(
            MessageLogModel(
                campaign_id=campaign.id,
                account_id=account.id,
                contact_id=contact.id,
                status="sent" if success else "failed",
                error_message=error,
            )
        )
        # NOTE: we deliberately do NOT touch the global
        # ``Contact.is_processed`` flag any more. Ad-hoc flows rely on
        # the MessageLog + the new CampaignRecipient table.
        await db.commit()
