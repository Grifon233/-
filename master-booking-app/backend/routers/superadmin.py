"""
Router для супер-админа: управление мастерами, подписками и метрики.
"""
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, date as date_type
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, delete, select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import (
    Master,
    MasterBot,
    Subscription,
    ArchitectFunnelEvent,
    UtmCampaign,
    UtmCampaignGroup,
    Client,
    Booking,
    get_db,
)
from backend.middleware.superadmin_auth import verify_superadmin
from backend.routers.subscription_admin import subscription_admin_service
from backend.services.data_deletion import delete_master_bot_data, delete_master_profile_data

router = APIRouter(prefix="/api/superadmin", tags=["superadmin"])
logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _subscription_end(subscription: Subscription | None) -> datetime | None:
    if not subscription or subscription.lifetime or not subscription.paid_at:
        return None
    return subscription.paid_at + timedelta(days=subscription.period_days or 0)


def _days_left(subscription: Subscription | None) -> int | None:
    end_at = _subscription_end(subscription)
    if not end_at:
        return None
    return max(0, (end_at.date() - datetime.utcnow().date()).days)


def _is_stale_pending_subscription(subscription: Subscription | None) -> bool:
    if not subscription:
        return False
    if subscription.status != "pending" or subscription.paid_at:
        return False
    return (subscription.created_at or datetime.utcnow()) <= datetime.utcnow() - timedelta(hours=2)

def _build_bot_row(bot: MasterBot, subscription: Subscription | None = None) -> dict:
    return {
        "id": bot.id,
        "username": bot.username,
        "status": bot.status,
        "created_at": bot.created_at.isoformat() if bot.created_at else None,
        "started_at": bot.started_at.isoformat() if bot.started_at else None,
        "subscription": _build_subscription_row(subscription),
    }


def _build_subscription_row(subscription: Subscription | None) -> dict | None:
    if not subscription:
        return None
    return {
        "id": subscription.id,
        "master_bot_id": subscription.master_bot_id,
        "status": subscription.status,
        "period_days": subscription.period_days,
        "price": subscription.price,
        "payment_provider": subscription.payment_provider,
        "paid_at": subscription.paid_at.isoformat() if subscription.paid_at else None,
        "ends_at": _subscription_end(subscription).isoformat() if _subscription_end(subscription) else None,
        "days_left": _days_left(subscription),
        "lifetime": bool(subscription.lifetime),
    }


def _build_master_row(master: Master, bot, subscription, clients_count: int, bookings_count: int, upcoming_count: int = 0, bots: list[dict] | None = None) -> dict:
    """Собирает dict для одной строки в списке мастеров."""
    return {
        "id": master.id,
        "name": master.name,
        "telegram_id": master.telegram_id,
        "telegram_username": master.telegram_username,
        "created_at": master.created_at.isoformat() if master.created_at else None,
        "is_demo": master.is_demo,
        "bot": _build_bot_row(bot, subscription) if bot else None,
        "bots": bots or [],
        "subscription": _build_subscription_row(subscription),
        "clients_count": clients_count,
        "bookings_count": bookings_count,
        "upcoming_bookings_count": upcoming_count,
    }


class SubscriptionUpdate(BaseModel):
    status: str = Field(default="active", pattern="^(active|frozen|expired)$")
    period_days: int = Field(default=30, ge=1, le=3650)
    price: int = Field(default=0, ge=0)
    lifetime: bool = False
    master_bot_id: int | None = None


class UtmCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    target_url: str = Field(min_length=8, max_length=2048)
    group_id: int | None = None


class UtmCampaignUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    placement_url: str | None = Field(default=None, max_length=2048)
    group_id: int | None = None


class UtmCampaignGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class UtmCampaignGroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


_CYRILLIC_SLUG_MAP = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def _slugify_utm_name(name: str) -> str:
    normalized = name.strip().lower()
    ad_match = re.search(r"(?:реклама|ad)\s*([0-9]+)", normalized)
    if ad_match:
        return f"ad{ad_match.group(1)}"
    normalized = normalized.translate(_CYRILLIC_SLUG_MAP)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized[:64] or "campaign"


async def _unique_utm_source(db: AsyncSession, name: str) -> str:
    base = _slugify_utm_name(name)
    source = base
    counter = 2
    while await db.scalar(select(func.count(UtmCampaign.id)).where(UtmCampaign.source == source)):
        source = f"{base}-{counter}"
        counter += 1
    return source


def _validate_target_url(url: str) -> str:
    value = url.strip()
    if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(/.*)?$", value, re.IGNORECASE):
        return f"https://{value}"
    if not re.match(r"^https?://", value, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Ссылка должна быть в формате https://site.ru или site.ru")
    return value


def _validate_optional_url(url: str | None) -> str | None:
    value = (url or "").strip()
    if not value:
        return None
    if not re.match(r"^(https?://)?[a-z0-9.-]+\.[a-z]{2,}(/.*)?$", value, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Ссылка должна быть в формате https://t.me/channel или t.me/channel")
    return value


async def _build_utm_campaign_row(db: AsyncSession, request: Request, campaign: UtmCampaign) -> dict:
    source = campaign.source
    group = await db.get(UtmCampaignGroup, campaign.group_id) if campaign.group_id else None
    clicks = await db.scalar(
        select(func.count(ArchitectFunnelEvent.id)).where(
            ArchitectFunnelEvent.event_type == "utm_click",
            ArchitectFunnelEvent.metadata_json["source"].as_string() == source,
        )
    ) or 0
    path_stats: list[dict] = []
    referrer_stats: list[dict] = []
    if source == "organic":
        organic_events = (await db.execute(
            select(ArchitectFunnelEvent.metadata_json).where(
                ArchitectFunnelEvent.event_type == "utm_click",
                ArchitectFunnelEvent.metadata_json["source"].as_string() == source,
            )
        )).scalars().all()
        path_counter: Counter[str] = Counter()
        referrer_counter: Counter[str] = Counter()
        for metadata in organic_events:
            metadata = metadata or {}
            path = (metadata.get("path") or "/").strip() or "/"
            referrer = (metadata.get("referrer") or "Прямой заход / поисковая выдача").strip()
            path_counter[path] += 1
            referrer_counter[referrer] += 1
        path_stats = [{"path": path, "clicks": count} for path, count in path_counter.most_common(12)]
        referrer_stats = [{"referrer": referrer, "clicks": count} for referrer, count in referrer_counter.most_common(12)]
    return {
        "id": campaign.id,
        "group_id": campaign.group_id,
        "group_name": group.name if group else None,
        "source": source,
        "name": campaign.name,
        "target_url": campaign.target_url,
        "placement_url": campaign.placement_url,
        "utm_url": f"{str(request.base_url).rstrip('/')}/api/utm/{source}",
        "active": bool(campaign.active),
        "clicks": clicks,
        "path_stats": path_stats,
        "referrer_stats": referrer_stats,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


def _build_utm_group_row(group: UtmCampaignGroup) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "sort_order": group.sort_order,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


async def _resolve_utm_group_id(db: AsyncSession, group_id: int | None) -> int | None:
    if group_id is None:
        return None
    group = await db.get(UtmCampaignGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Группа UTM-ссылок не найдена")
    return group.id


def _build_booking_row(booking: Booking, client: Client, master: Master) -> dict:
    return {
        "id": booking.id,
        "master_id": master.id,
        "master_name": master.name,
        "client_name": client.name,
        "client_phone": client.phone,
        "client_telegram_id": client.telegram_id,
        "date": booking.date.isoformat(),
        "time": booking.time.strftime("%H:%M"),
        "duration_minutes": booking.duration_minutes,
        "service_name": booking.service_name,
        "status": booking.status,
        "comment": booking.comment,
        "master_comment": booking.master_comment,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }


# ─── endpoints ───────────────────────────────────────────────────────────────

@router.get("/auth-check")
async def auth_check(request: Request, db: AsyncSession = Depends(get_db)):
    """Проверка авторизации супер-админа."""
    tg_user = await verify_superadmin(request, db)
    return {"authorized": True, "user": tg_user}


@router.get("/metrics")
async def get_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    period: str = Query("all", description="Период: all, 6m, 1m, 1w, 1d"),
):
    """Агрегированные метрики платформы."""
    await verify_superadmin(request, db)

    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    cutoff_map = {
        "1d": today_start,
        "1w": today_start - timedelta(days=6),
        "1m": today_start - timedelta(days=29),
        "6m": today_start - timedelta(days=181),
    }
    cutoff = cutoff_map.get(period)  # None = всё время

    # Masters
    total_masters = await db.scalar(select(func.count(Master.id)).where(Master.is_demo == False))
    real_master_telegram_ids = select(Master.telegram_id).where(
        Master.is_demo == False,
        Master.telegram_id.isnot(None),
    )
    # Активные — те, у кого есть активная подписка
    active_subs = await db.execute(
        select(Subscription.master_telegram_id)
        .where(
            Subscription.status == "active",
            Subscription.master_telegram_id.in_(real_master_telegram_ids),
        )
        .distinct()
    )
    active_master_ids = {row[0] for row in active_subs.all()}
    masters_with_sub = await db.execute(
        select(Master.id).where(Master.telegram_id.in_(active_master_ids), Master.is_demo == False)
    )
    active_master_id_set = {row[0] for row in masters_with_sub.all()}
    active_masters = await db.scalar(select(func.count(Master.id)).where(Master.id.in_(active_master_id_set)))

    new_in_period_q = select(func.count(Master.id)).where(Master.is_demo == False)
    if cutoff is not None:
        new_in_period_q = new_in_period_q.where(Master.created_at >= cutoff)
    new_in_period = await db.scalar(new_in_period_q)

    # Subscriptions
    active_subs_q = await db.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.status == "active",
            Subscription.master_telegram_id.in_(real_master_telegram_ids),
        )
    )
    pending_subs_q = await db.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.status == "pending",
            Subscription.created_at > datetime.utcnow() - timedelta(hours=2),
            Subscription.master_telegram_id.in_(real_master_telegram_ids),
        )
    )
    frozen_subs_q = await db.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.status == "frozen",
            Subscription.master_telegram_id.in_(real_master_telegram_ids),
        )
    )
    expired_subs_q = await db.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.status == "expired",
            Subscription.master_telegram_id.in_(real_master_telegram_ids),
        )
    )
    # Revenue for the selected period (or all time if period == "all")
    rev_q = select(func.sum(Subscription.price)).where(
        Subscription.status.in_(["active", "expired"]),
        Subscription.paid_at.isnot(None),
        Subscription.master_telegram_id.in_(real_master_telegram_ids),
    )
    if cutoff is not None:
        rev_q = rev_q.where(Subscription.paid_at >= cutoff)
    revenue = (await db.execute(rev_q)).scalar() or 0

    # Bots
    total_bots = await db.scalar(select(func.count(MasterBot.id)))
    working_bots = await db.scalar(
        select(func.count(MasterBot.id)).where(MasterBot.status == "running")
    )
    error_bots = await db.scalar(
        select(func.count(MasterBot.id)).where(MasterBot.status.in_(["error", "crashed"]))
    )

    # Bookings
    bookings_this_month = await db.scalar(
        select(func.count(Booking.id)).join(Master).where(Booking.date >= month_start.date(), Master.is_demo == False)
    )
    bookings_today = await db.scalar(
        select(func.count(Booking.id)).join(Master).where(Booking.date == now.date(), Master.is_demo == False)
    )
    bookings_this_week = await db.scalar(
        select(func.count(Booking.id)).join(Master).where(Booking.date >= week_start.date(), Master.is_demo == False)
    )
    upcoming_bookings = await db.scalar(
        select(func.count(Booking.id)).join(Master).where(Booking.status.in_(["upcoming", "confirmed"]), Master.is_demo == False)
    )
    cancelled_bookings = await db.scalar(
        select(func.count(Booking.id)).join(Master).where(Booking.status == "cancelled", Master.is_demo == False)
    )
    total_clients = await db.scalar(select(func.count(Client.id)).join(Master).where(Master.is_demo == False))

    # Conversion funnel — filtered by period
    def _funnel_q(event_type: str):
        q = select(func.count(func.distinct(ArchitectFunnelEvent.telegram_id))).where(
            ArchitectFunnelEvent.event_type == event_type
        )
        if cutoff is not None:
            q = q.where(ArchitectFunnelEvent.created_at >= cutoff)
        return q

    started_users = await db.scalar(_funnel_q("architect_start")) or 0
    created_users = await db.scalar(_funnel_q("bot_created")) or 0
    unpaid_deleted_users = await db.scalar(_funnel_q("trial_bot_deleted_unpaid")) or 0
    paid_users = await db.scalar(_funnel_q("subscription_paid")) or 0

    def percent(part: int, total: int) -> float:
        return round((part / total) * 100, 1) if total else 0.0

    return {
        "masters": {
            "total": total_masters or 0,
            "active": active_masters or 0,
            "newInPeriod": new_in_period or 0,
        },
        "subscriptions": {
            "active": active_subs_q or 0,
            "frozen": frozen_subs_q or 0,
            "expired": expired_subs_q or 0,
            "pending": pending_subs_q or 0,
            "revenue": revenue,
        },
        "bots": {
            "total": total_bots or 0,
            "working": working_bots or 0,
            "errors": error_bots or 0,
        },
        "bookings": {
            "thisMonth": bookings_this_month or 0,
            "today": bookings_today or 0,
            "thisWeek": bookings_this_week or 0,
            "upcoming": upcoming_bookings or 0,
            "cancelled": cancelled_bookings or 0,
        },
        "clients": {"total": total_clients or 0},
        "conversion": {
            "started": started_users,
            "startNoBot": max(started_users - created_users, 0),
            "created": created_users,
            "createdNoPaidDeleted": unpaid_deleted_users,
            "paid": paid_users,
            "createRate": percent(created_users, started_users),
            "payRateFromStart": percent(paid_users, started_users),
            "payRateFromCreated": percent(paid_users, created_users),
        },
    }


@router.get("/masters")
async def get_masters(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by subscription status: active, frozen, expired, none"),
):
    """Список всех мастеров с информацией о боте и подписке."""
    await verify_superadmin(request, db)

    # Получаем всех мастеров
    result = await db.execute(select(Master).order_by(Master.created_at.desc()))
    masters = result.scalars().all()

    owner_masters: dict[int, Master] = {}
    for master in masters:
        if master.telegram_id is not None and master.telegram_id not in owner_masters:
            owner_masters[master.telegram_id] = master

    bot_rows_result = await db.execute(
        select(MasterBot).order_by(MasterBot.created_at.desc())
    )
    all_bots = bot_rows_result.scalars().all()
    bots_by_owner: dict[int, list[MasterBot]] = {}
    group_master_ids: dict[int, set[int]] = {}
    for bot in all_bots:
        bots_by_owner.setdefault(bot.master_telegram_id, []).append(bot)
        group_master_ids.setdefault(bot.master_telegram_id, set())
        if bot.master_id:
            group_master_ids[bot.master_telegram_id].add(bot.master_id)
    for master in masters:
        if master.telegram_id is not None:
            group_master_ids.setdefault(master.telegram_id, set()).add(master.id)
        elif master.is_demo:
            group_master_ids.setdefault(master.id, set()).add(master.id)
            owner_masters.setdefault(master.id, master)

    grouped_master_ids = sorted({master_id for ids in group_master_ids.values() for master_id in ids})

    clients_counts = {}
    bookings_counts = {}
    if grouped_master_ids:
        clients_result = await db.execute(
            select(Client.master_id, func.count(Client.id))
            .where(Client.master_id.in_(grouped_master_ids))
            .group_by(Client.master_id)
        )
        for master_id, count in clients_result.all():
            clients_counts[master_id] = count

        bookings_result = await db.execute(
            select(
                Booking.master_id,
                func.count(Booking.id),
                func.sum(Booking.status.in_(["upcoming", "confirmed"]).cast(Integer)),
            )
            .where(Booking.master_id.in_(grouped_master_ids))
            .group_by(Booking.master_id)
        )
        upcoming_counts = {}
        for master_id, count, upcoming_count in bookings_result.all():
            bookings_counts[master_id] = count
            upcoming_counts[master_id] = upcoming_count or 0
    else:
        upcoming_counts = {}

    # Получаем подписки и ботов
    tg_ids = [tg_id for tg_id in owner_masters.keys() if isinstance(tg_id, int)]
    subscriptions = {}
    subscriptions_by_bot = {}
    if tg_ids:
        sub_result = await db.execute(
            select(Subscription)
            .where(Subscription.master_telegram_id.in_(tg_ids))
            .order_by(Subscription.created_at.desc())
        )
        for sub in sub_result.scalars().all():
            if _is_stale_pending_subscription(sub):
                continue
            subscriptions.setdefault(sub.master_telegram_id, sub)
            if sub.master_bot_id:
                subscriptions_by_bot.setdefault(sub.master_bot_id, sub)

    rows = []
    for tg_id, master in owner_masters.items():
        sub = subscriptions.get(tg_id)
        master_bots = bots_by_owner.get(tg_id, [])
        bot = master_bots[0] if master_bots else None
        related_master_ids = group_master_ids.get(tg_id, {master.id})
        clients_count = sum(clients_counts.get(master_id, 0) for master_id in related_master_ids)
        bookings_count = sum(bookings_counts.get(master_id, 0) for master_id in related_master_ids)
        upcoming_count = sum(upcoming_counts.get(master_id, 0) for master_id in related_master_ids)

        # Filter by subscription status if requested
        if status is not None:
            if status == "none" and sub is not None:
                continue
            if status != "none" and (sub is None or sub.status != status):
                continue

        shared_sub = sub if sub and sub.master_bot_id is None else None
        bot_rows = [_build_bot_row(item, subscriptions_by_bot.get(item.id) or shared_sub) for item in master_bots]
        rows.append(_build_master_row(master, bot, sub, clients_count, bookings_count, upcoming_count, bot_rows))

    return {"masters": rows}


@router.get("/masters/{master_id}")
async def get_master(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Данные одного мастера."""
    await verify_superadmin(request, db)

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    tg_id = master.telegram_id
    sub = None
    bot = None
    master_bots = []
    subscriptions_by_bot = {}
    if tg_id:
        sub_result = await db.execute(
            select(Subscription)
            .where(Subscription.master_telegram_id == tg_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        sub = sub_result.scalar_one_or_none()
        all_subs_result = await db.execute(
            select(Subscription)
            .where(Subscription.master_telegram_id == tg_id)
            .order_by(Subscription.created_at.desc())
        )
        for item in all_subs_result.scalars().all():
            if _is_stale_pending_subscription(item):
                continue
            if item.master_bot_id:
                subscriptions_by_bot.setdefault(item.master_bot_id, item)
        bot_result = await db.execute(
            select(MasterBot)
            .where(MasterBot.master_telegram_id == tg_id)
            .order_by(MasterBot.created_at.desc())
        )
        master_bots = list(bot_result.scalars().all())
        bot = master_bots[0] if master_bots else None

    related_master_ids = {master.id}
    for item in master_bots:
        if item.master_id:
            related_master_ids.add(item.master_id)
    clients_count = await db.scalar(
        select(func.count(Client.id)).where(Client.master_id.in_(related_master_ids))
    )
    bookings_count = await db.scalar(
        select(func.count(Booking.id)).where(Booking.master_id.in_(related_master_ids))
    )
    upcoming_count = await db.scalar(
        select(func.count(Booking.id)).where(
            Booking.master_id.in_(related_master_ids),
            Booking.status.in_(["upcoming", "confirmed"]),
        )
    )

    shared_sub = sub if sub and sub.master_bot_id is None else None
    bot_rows = [_build_bot_row(item, subscriptions_by_bot.get(item.id) or shared_sub) for item in master_bots]
    row = _build_master_row(master, bot, sub, clients_count or 0, bookings_count or 0, upcoming_count or 0, bot_rows)
    recent_result = await db.execute(
        select(Booking, Client)
        .join(Client, Booking.client_id == Client.id)
        .where(Booking.master_id.in_(related_master_ids))
        .order_by(Booking.date.desc(), Booking.time.desc())
        .limit(8)
    )
    row["recent_bookings"] = [_build_booking_row(booking, client, master) for booking, client in recent_result.all()]
    return row


@router.post("/masters/{master_id}/freeze")
async def freeze_master(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Заморозить подписку мастера."""
    await verify_superadmin(request, db)

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    if not master.telegram_id:
        raise HTTPException(status_code=400, detail="Master has no telegram_id")

    result = await db.execute(
        select(Subscription)
        .where(Subscription.master_telegram_id == master.telegram_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "frozen"
    await db.commit()

    # Синхронизируем статус MasterBot через subscription_admin_service
    try:
        await subscription_admin_service.sync_status(master.telegram_id, "frozen")
    except Exception as e:
        logger.error(f"Failed to sync frozen status for master {master.telegram_id}: {e}")

    return {"success": True, "master_id": master_id, "status": "frozen"}


@router.post("/masters/{master_id}/unfreeze")
async def unfreeze_master(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Разморозить подписку мастера."""
    await verify_superadmin(request, db)

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    if not master.telegram_id:
        raise HTTPException(status_code=400, detail="Master has no telegram_id")

    result = await db.execute(
        select(Subscription)
        .where(Subscription.master_telegram_id == master.telegram_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription.status = "active"
    await db.commit()

    # Синхронизируем статус MasterBot и устанавливаем webhook через subscription_admin_service
    try:
        await subscription_admin_service.sync_status(master.telegram_id, "active")
    except Exception as e:
        logger.error(f"Failed to sync unfrozen status for master {master.telegram_id}: {e}")

    return {"success": True, "master_id": master_id, "status": "active"}


@router.post("/masters/{master_id}/extend")
async def extend_subscription(
    master_id: int,
    request: Request,
    days: int = Query(..., ge=1, le=365, description="Number of days to extend"),
    db: AsyncSession = Depends(get_db),
):
    """Продлить подписку мастера на N дней."""
    await verify_superadmin(request, db)

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    if not master.telegram_id:
        raise HTTPException(status_code=400, detail="Master has no telegram_id")

    result = await db.execute(
        select(Subscription)
        .where(Subscription.master_telegram_id == master.telegram_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        subscription = Subscription(
            master_telegram_id=master.telegram_id,
            period_days=days,
            price=0,
            payment_provider="manual",
            status="active",
            paid_at=datetime.utcnow(),
        )
        db.add(subscription)
        await db.commit()
        try:
            await subscription_admin_service.sync_status(master.telegram_id, "active")
        except Exception as e:
            logger.error("Failed to sync new manual subscription for %s: %s", master.telegram_id, e)
        return {"success": True, "master_id": master_id, "period_days": subscription.period_days}

    previous_status = subscription.status
    # Продлеваем от текущего конца подписки, а если она уже истекла —
    # от текущего момента. Иначе "продление" истёкшей подписки не давало
    # реальных дней (срок считается как paid_at + period_days).
    now = datetime.utcnow()
    if subscription.lifetime:
        # Бессрочную продлевать не нужно.
        await db.commit()
        return {"success": True, "master_id": master_id, "period_days": subscription.period_days}
    current_end = _subscription_end(subscription)
    base = current_end if (current_end and current_end > now) else now
    new_end = base + timedelta(days=days)
    subscription.paid_at = now
    subscription.period_days = max(1, (new_end - now).days)
    subscription.status = "active"
    await db.commit()

    # Если подписка была frozen — размораживаем бота
    if previous_status == "frozen":
        try:
            await subscription_admin_service.sync_status(master.telegram_id, "active")
        except Exception as e:
            logger.error(f"Failed to sync unfrozen status after extend for master {master.telegram_id}: {e}")

    return {"success": True, "master_id": master_id, "period_days": subscription.period_days}


@router.put("/masters/{master_id}/subscription")
async def set_subscription(
    master_id: int,
    request: Request,
    payload: SubscriptionUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Create or replace a manual subscription for support operations."""
    await verify_superadmin(request, db)
    master = await db.get(Master, master_id)
    if not master or not master.telegram_id:
        raise HTTPException(status_code=404, detail="Master with Telegram ID not found")
    if payload.master_bot_id is not None:
        bot = await db.get(MasterBot, payload.master_bot_id)
        if not bot or bot.master_telegram_id != master.telegram_id:
            raise HTTPException(status_code=404, detail="Bot does not belong to master")

    # "Create or replace": гасим прежние действующие подписки этого мастера,
    # чтобы не копились дубли active/pending (иначе ломается учёт и метрики).
    superseded_filter = [
        Subscription.master_telegram_id == master.telegram_id,
        Subscription.status.in_(["active", "pending", "frozen"]),
    ]
    if payload.master_bot_id is not None:
        superseded_filter.append(Subscription.master_bot_id == payload.master_bot_id)
    existing_subs = (await db.execute(select(Subscription).where(*superseded_filter))).scalars().all()
    for old_sub in existing_subs:
        old_sub.status = "expired"

    subscription = Subscription(
        master_telegram_id=master.telegram_id,
        master_bot_id=payload.master_bot_id,
        period_days=payload.period_days,
        price=payload.price,
        payment_provider="manual",
        status=payload.status,
        paid_at=datetime.utcnow() if payload.status == "active" else None,
        lifetime=payload.lifetime,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    try:
        await subscription_admin_service.sync_status(master.telegram_id, "active" if payload.status == "active" else "frozen", payload.master_bot_id)
    except Exception as e:
        logger.error("Failed to sync manual subscription for %s: %s", master.telegram_id, e)

    return {"success": True, "subscription_id": subscription.id, "status": subscription.status}


@router.delete("/masters/{master_id}")
async def delete_master(
    master_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Удалить мастера и все связанные данные."""
    await verify_superadmin(request, db)

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    if master.is_demo:
        raise HTTPException(status_code=403, detail="Cannot delete demo master")

    # Проверяем наличие активных записей перед удалением
    active_bookings = await db.scalar(
        select(func.count(Booking.id)).where(
            Booking.master_id == master_id,
            Booking.status.in_(["upcoming", "confirmed"])
        )
    )
    if active_bookings and active_bookings > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete master with {active_bookings} active booking(s). Cancel or complete all bookings first."
        )

    await delete_master_profile_data(db, master)
    await db.commit()

    return {"success": True, "master_id": master_id}


@router.delete("/bots/{bot_id}")
async def delete_bot(
    bot_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Удалить только бота мастера по ID.

    Профиль мастера, подписка, клиенты и записи остаются в базе.
    """
    await verify_superadmin(request, db)

    bot = await db.get(MasterBot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    master_telegram_id = bot.master_telegram_id
    username = bot.username

    # Снимаем webhook бота. Если Telegram недоступен, всё равно удаляем запись из БД.
    from backend.token_utils import decrypt_token
    raw_token = decrypt_token(bot.token)
    if raw_token:
        b = None
        try:
            from aiogram import Bot
            from aiogram.client.session.aiohttp import AiohttpSession
            from architect.config import settings
            proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url
            session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
            b = Bot(token=raw_token, session=session)
            await b.delete_webhook(drop_pending_updates=True, request_timeout=10)
        except Exception as e:
            logger.warning(f"Failed to delete webhook for bot {bot_id}: {e}")
        finally:
            if b:
                await b.session.close()

    await delete_master_bot_data(db, bot)
    await db.commit()
    logger.info(f"Bot {bot_id} (@{username}) deleted by superadmin")

    return {
        "success": True,
        "bot_id": bot_id,
        "master_telegram_id": master_telegram_id,
    }


@router.get("/bookings")
async def get_bookings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    status: Optional[str] = Query(None),
    master_id: Optional[int] = Query(None),
    include_demo: bool = False,
    limit: int = Query(200, ge=1, le=500),
):
    """Operational booking list across all masters."""
    await verify_superadmin(request, db)
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    query = (
        select(Booking, Client, Master)
        .join(Client, Booking.client_id == Client.id)
        .join(Master, Booking.master_id == Master.id)
        .where(Booking.date >= cutoff)
        .order_by(Booking.date.desc(), Booking.time.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Booking.status == status)
    if master_id:
        query = query.where(Booking.master_id == master_id)
    if not include_demo:
        query = query.where(Master.is_demo == False)
    result = await db.execute(query)
    return {"bookings": [_build_booking_row(booking, client, master) for booking, client, master in result.all()]}


@router.get("/payments")
async def get_payments(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
):
    """Payment and manual subscription history."""
    await verify_superadmin(request, db)
    query = select(Subscription).order_by(Subscription.created_at.desc()).limit(limit)
    if status:
        query = query.where(Subscription.status == status)
    result = await db.execute(query)
    subscriptions = [sub for sub in result.scalars().all() if not _is_stale_pending_subscription(sub)]
    return {
        "payments": [
            {
                "id": sub.id,
                "master_telegram_id": sub.master_telegram_id,
                "status": sub.status,
                "period_days": sub.period_days,
                "lifetime": bool(sub.lifetime),
                "price": sub.price,
                "payment_provider": sub.payment_provider,
                "payment_id": sub.payment_id,
                "telegram_payment_charge_id": sub.telegram_payment_charge_id,
                "provider_payment_charge_id": sub.provider_payment_charge_id,
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
                "paid_at": sub.paid_at.isoformat() if sub.paid_at else None,
                "ends_at": _subscription_end(sub).isoformat() if _subscription_end(sub) else None,
            }
            for sub in subscriptions
        ]
    }


@router.get("/events")
async def get_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    event_type: Optional[str] = Query(None, description="Filter by type: master_created, payment, bot_error, master_deleted"),
):
    """
    Журнал активности за последние N дней.
    Типы событий:
    - master_created: новый мастер зарегистрирован
    - payment: поступила оплата подписки
    - bot_error: у бота мастера статус error/crashed
    - master_deleted: мастер удалён
    """
    await verify_superadmin(request, db)

    cutoff = datetime.utcnow() - timedelta(days=days)
    events = []

    # master_created
    if event_type is None or event_type == "master_created":
        result = await db.execute(
            select(Master).where(Master.created_at >= cutoff, Master.is_demo == False).order_by(Master.created_at.desc())
        )
        for m in result.scalars().all():
            events.append({
                "type": "master_created",
                "timestamp": m.created_at.isoformat(),
                "master_id": m.id,
                "master_name": m.name,
                "telegram_id": m.telegram_id,
            })

    # payment
    if event_type is None or event_type == "payment":
        result = await db.execute(
            select(Subscription)
            .where(Subscription.paid_at >= cutoff, Subscription.paid_at.isnot(None))
            .order_by(Subscription.paid_at.desc())
        )
        for s in result.scalars().all():
            events.append({
                "type": "payment",
                "timestamp": s.paid_at.isoformat(),
                "subscription_id": s.id,
                "master_telegram_id": s.master_telegram_id,
                "amount": s.price,
                "payment_id": s.payment_id,
            })

    # bot_error
    if event_type is None or event_type == "bot_error":
        result = await db.execute(
            select(MasterBot).where(
                MasterBot.status.in_(["error", "crashed"])
            ).order_by(MasterBot.created_at.desc())
        )
        for b in result.scalars().all():
            # include if created within cutoff OR still in error state
            if b.created_at >= cutoff:
                events.append({
                    "type": "bot_error",
                    "timestamp": b.created_at.isoformat(),
                    "bot_id": b.id,
                    "master_telegram_id": b.master_telegram_id,
                    "bot_username": b.username,
                    "bot_status": b.status,
                })

    # Sort by timestamp descending
    events.sort(key=lambda e: e["timestamp"], reverse=True)

    return {"events": events[:200]}  # limit to 200 most recent


@router.get("/utm-stats")
async def get_utm_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """UTM статистика: клики и старты по источникам."""
    await verify_superadmin(request, db)
    campaigns = (await db.execute(
        select(UtmCampaign).order_by(UtmCampaign.created_at.asc(), UtmCampaign.id.asc())
    )).scalars().all()
    result = {}
    for campaign in campaigns:
        source = campaign.source
        clicks = await db.scalar(
            select(func.count(ArchitectFunnelEvent.id)).where(
                ArchitectFunnelEvent.event_type == "utm_click",
                ArchitectFunnelEvent.metadata_json["source"].as_string() == source,
            )
        ) or 0
        result[source] = {"clicks": clicks}
    return result


@router.get("/utm-campaigns")
async def get_utm_campaigns(request: Request, db: AsyncSession = Depends(get_db)):
    """Список UTM-кампаний с готовыми ссылками и статистикой."""
    await verify_superadmin(request, db)
    groups = (await db.execute(
        select(UtmCampaignGroup).order_by(UtmCampaignGroup.sort_order.asc(), UtmCampaignGroup.created_at.asc(), UtmCampaignGroup.id.asc())
    )).scalars().all()
    campaigns = (await db.execute(
        select(UtmCampaign).order_by(UtmCampaign.created_at.asc(), UtmCampaign.id.asc())
    )).scalars().all()
    rows = [await _build_utm_campaign_row(db, request, campaign) for campaign in campaigns]
    return {"groups": [_build_utm_group_row(group) for group in groups], "campaigns": rows}


@router.post("/utm-campaigns")
async def create_utm_campaign(payload: UtmCampaignCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Создать новую рекламную UTM-ссылку."""
    await verify_superadmin(request, db)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название рекламы")
    target_url = _validate_target_url(payload.target_url)
    group_id = await _resolve_utm_group_id(db, payload.group_id)
    source = await _unique_utm_source(db, name)
    campaign = UtmCampaign(
        group_id=group_id,
        source=source,
        name=name,
        target_url=target_url,
        active=True,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return await _build_utm_campaign_row(db, request, campaign)


@router.patch("/utm-campaigns/{campaign_id}")
async def update_utm_campaign(
    campaign_id: int,
    payload: UtmCampaignUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Изменить название кампании и ссылку на площадку размещения."""
    await verify_superadmin(request, db)
    campaign = await db.get(UtmCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="UTM-ссылка не найдена")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название рекламы")
    campaign.name = name
    campaign.placement_url = _validate_optional_url(payload.placement_url)
    campaign.group_id = await _resolve_utm_group_id(db, payload.group_id)
    await db.commit()
    await db.refresh(campaign)
    return await _build_utm_campaign_row(db, request, campaign)


@router.delete("/utm-campaigns/{campaign_id}")
async def delete_utm_campaign(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Удалить старую UTM-ссылку из списка и отключить редирект."""
    await verify_superadmin(request, db)
    campaign = await db.get(UtmCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="UTM-ссылка не найдена")
    await db.delete(campaign)
    await db.commit()
    return {"ok": True}


@router.delete("/utm-campaigns/{campaign_id}/stats")
async def reset_utm_campaign_stats(campaign_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Обнулить счётчик переходов конкретной UTM-ссылки."""
    await verify_superadmin(request, db)
    campaign = await db.get(UtmCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="UTM-ссылка не найдена")
    await db.execute(
        delete(ArchitectFunnelEvent).where(
            ArchitectFunnelEvent.event_type == "utm_click",
            ArchitectFunnelEvent.metadata_json["source"].as_string() == campaign.source,
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/utm-groups")
async def create_utm_group(payload: UtmCampaignGroupCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Создать группу рекламных кампаний."""
    await verify_superadmin(request, db)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название группы")
    max_order = await db.scalar(select(func.max(UtmCampaignGroup.sort_order))) or 0
    group = UtmCampaignGroup(name=name, sort_order=max_order + 10)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _build_utm_group_row(group)


@router.patch("/utm-groups/{group_id}")
async def update_utm_group(group_id: int, payload: UtmCampaignGroupUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    """Переименовать группу рекламных кампаний."""
    await verify_superadmin(request, db)
    group = await db.get(UtmCampaignGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Группа UTM-ссылок не найдена")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название группы")
    group.name = name
    await db.commit()
    await db.refresh(group)
    return _build_utm_group_row(group)


@router.delete("/utm-groups/{group_id}")
async def delete_utm_group(group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Удалить группу, не удаляя кампании внутри неё."""
    await verify_superadmin(request, db)
    group = await db.get(UtmCampaignGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Группа UTM-ссылок не найдена")
    campaigns = (await db.execute(select(UtmCampaign).where(UtmCampaign.group_id == group_id))).scalars().all()
    for campaign in campaigns:
        campaign.group_id = None
    await db.delete(group)
    await db.commit()
    return {"ok": True}


@router.delete("/funnel-events")
async def reset_funnel_events(request: Request, db: AsyncSession = Depends(get_db)):
    """Сброс всей статистики воронки к нулям."""
    await verify_superadmin(request, db)
    await db.execute(delete(ArchitectFunnelEvent))
    await db.commit()
    return {"ok": True}
