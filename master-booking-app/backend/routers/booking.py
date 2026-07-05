from datetime import date, time, datetime as dt, timedelta
from typing import Annotated, Optional
import asyncio
from contextlib import asynccontextmanager
import hashlib
from html import escape
import logging
import os
import re
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import Booking, Client, Service, BlockedTime, Master, MasterBot, VkBot, VkClientProfile, get_db, BookingStatusHistory, SlotHold
from backend.client_profiles import ensure_master_client, get_client_profile, telegram_profile_url, verify_client_access
from backend.vk.auth import verify_vk_client_access
from backend.vk import api as vk_api
from backend.schemas.schemas import ApiResponse
from backend.middleware.tg_auth import verify_master_access, verify_telegram_init_data
from backend.rate_limiter import rate_limiter
from backend.time_utils import END_OF_DAY, time_to_minutes, time_overlaps, interval_end, is_schedule_date_excluded, resolve_day_schedule

router = APIRouter(prefix="/bookings", tags=["bookings"])

logger = logging.getLogger(__name__)
_sqlite_booking_lock = asyncio.Lock()


def _price_to_int(value: str | None) -> int:
    """Extract the first displayed ruble amount without joining unrelated digits."""
    if (value or "").lstrip().startswith("-"):
        return 0
    match = re.search(r"\d[\d\s]*(?:[.,]\d{1,2})?", value or "")
    if not match:
        return 0
    normalized = match.group(0).replace(" ", "").replace(",", ".")
    return int(float(normalized))


def _stable_lock_key(master_id: int, booking_date: date, slot_hash: int) -> int:
    """Стабильный 64-bit ключ для pg_try_advisory_xact_lock.
    Использует SHA-256, не hash() — стабилен между процессами."""
    raw = f"{master_id}:{booking_date.isoformat()}:{slot_hash}".encode()
    digest = hashlib.sha256(raw).digest()
    # PostgreSQL bigint is signed 64-bit.
    return int.from_bytes(digest[:8], "big", signed=True)


async def acquire_slot_lock(
    db: AsyncSession,
    master_id: int,
    booking_date: date,
    slot_hash: int,
) -> bool:
    """Advisory lock для дня мастера на время транзакции.
    PostgreSQL: pg_try_advisory_xact_lock со стабильным signed 64-bit ключом.
    SQLite: не поддерживает advisory locks — защита рассчитана на PostgreSQL.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite — без DB-level concurrency защиты.
        # Повторная проверка внутри транзакции ловит race в single-worker.
        return True

    # Все записи мастера за дату должны сериализоваться одним lock:
    # интервалы с разными стартами тоже могут пересекаться.
    lock_key = _stable_lock_key(master_id, booking_date, 0)
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key}
    )
    return bool(result.scalar())


def _master_tz(master: Master) -> ZoneInfo:
    try:
        return ZoneInfo(master.timezone or "Europe/Moscow")
    except Exception:
        return ZoneInfo("Europe/Moscow")


def _master_now(master: Master) -> dt:
    """Текущий момент в часовом поясе мастера (а не сервера)."""
    return dt.now(_master_tz(master))


def _validate_schedule_interval(
    master: Master,
    booking_date: date,
    booking_time: time,
    duration_minutes: int,
    allow_workday_overrun: bool = False,
) -> time:
    """Validate a requested interval against the master's working schedule."""
    local_tz = _master_tz(master)
    local_now = dt.now(local_tz)
    if dt.combine(booking_date, booking_time, tzinfo=local_tz) < local_now:
        raise HTTPException(status_code=400, detail="Cannot book in the past")

    end_mins = time_to_minutes(booking_time) + duration_minutes
    if end_mins > 24 * 60:
        raise HTTPException(status_code=400, detail="Booking end time is outside the day")
    # Конец ровно в полночь (24:00) допустим: внутренне представляем как 23:59:59,
    # чтобы сравнения интервалов оставались корректными.
    end_time = END_OF_DAY if end_mins == 24 * 60 else time(end_mins // 60, end_mins % 60)

    schedule = master.schedule_json or {}
    booking_days = min(int(schedule.get("booking_days", 90)), 90)
    if booking_date > local_now.date() + timedelta(days=booking_days):
        raise HTTPException(status_code=400, detail="This date is outside the open booking period")
    if is_schedule_date_excluded(schedule, booking_date):
        raise HTTPException(status_code=400, detail="This date is disabled by the master")
    day_schedule = resolve_day_schedule(schedule, booking_date)
    if not day_schedule or not day_schedule.get("active"):
        raise HTTPException(status_code=400, detail="Master does not work on this day")

    try:
        work_start = dt.strptime(day_schedule.get("work_start") or "00:00", "%H:%M").time()
        work_end = dt.strptime(day_schedule.get("work_end") or "23:59", "%H:%M").time()
        break_start = dt.strptime(day_schedule.get("break_start", "13:00"), "%H:%M").time()
        break_end = dt.strptime(day_schedule.get("break_end", "14:00"), "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=500, detail="Master schedule is invalid")

    if booking_time < work_start or booking_time >= work_end or (end_time > work_end and not allow_workday_overrun):
        raise HTTPException(status_code=400, detail="Time is outside master's working hours")
    if day_schedule.get("break_active", True) is not False and break_start < break_end and time_overlaps(booking_time, end_time, break_start, break_end):
        raise HTTPException(status_code=400, detail="Time overlaps with lunch break")

    return end_time


def _booking_exceeds_workday(master: Master, booking: Booking) -> bool:
    schedule = master.schedule_json or {}
    day_schedule = resolve_day_schedule(schedule, booking.date)
    if not day_schedule:
        return False
    work_end = dt.strptime(day_schedule.get("work_end") or "23:59", "%H:%M").time()
    return time_to_minutes(booking.time) + booking.duration_minutes > time_to_minutes(work_end)


async def _get_master_bot_token(db: AsyncSession, master_id: int, master_bot_id: int | None = None) -> str:
    master = await db.get(Master, master_id)
    if not master:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    from backend.token_utils import decrypt_token

    query = select(MasterBot.token).where(MasterBot.status == "running")
    if master_bot_id:
        query = query.where(MasterBot.id == master_bot_id)
    elif getattr(master, "telegram_id", None):
        query = query.where(
            (MasterBot.master_id == master.id) | (MasterBot.master_telegram_id == master.telegram_id)
        )
    else:
        query = query.where(MasterBot.master_id == master.id)
    result = await db.execute(query)
    bot_token = result.scalars().first()
    if bot_token:
        return decrypt_token(bot_token)

    # Some legacy/restored bookings may point to a bot row that was already
    # deleted. For notifications, fall back only inside the same master profile.
    if master_bot_id:
        fallback_result = await db.execute(
            select(MasterBot.token).where(
                MasterBot.master_id == master.id,
                MasterBot.status == "running",
            )
        )
        fallback_token = fallback_result.scalars().first()
        if fallback_token:
            logger.warning(
                "Booking notification fallback: master_bot_id=%s is unavailable, using active bot for master_id=%s",
                master_bot_id,
                master.id,
            )
            return decrypt_token(fallback_token)
        return ""
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


async def _get_master_owner_chat_id(db: AsyncSession, master: Master, master_bot_id: int | None = None) -> int | None:
    if getattr(master, "telegram_id", None):
        return master.telegram_id
    query = select(MasterBot.master_telegram_id).where(MasterBot.status == "running")
    if master_bot_id:
        query = query.where(MasterBot.id == master_bot_id)
    else:
        query = query.where(MasterBot.master_id == master.id)
    result = await db.execute(query)
    owner_chat_id = result.scalars().first()
    if owner_chat_id:
        return owner_chat_id
    if master_bot_id:
        fallback_result = await db.execute(
            select(MasterBot.master_telegram_id).where(
                MasterBot.master_id == master.id,
                MasterBot.status == "running",
            )
        )
        fallback_owner_chat_id = fallback_result.scalars().first()
        if fallback_owner_chat_id:
            logger.warning(
                "Owner notification fallback: master_bot_id=%s is unavailable, using active bot owner for master_id=%s",
                master_bot_id,
                master.id,
            )
        return fallback_owner_chat_id
    return None


async def _send_telegram(token: str, chat_id: int, text: str) -> bool:
    if not token or not chat_id:
        return False
    try:
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("PROXY_URL")
        client_kwargs = {"timeout": 20.0}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            if response.status_code != 200:
                logger.warning(
                    "Telegram sendMessage failed: chat_id=%s status=%s body=%s",
                    chat_id,
                    response.status_code,
                    response.text[:500],
                )
                return False
            return True
    except Exception as e:
        logger.warning(f"Failed to send Telegram message: {e}")
        return False


async def _client_profile_url(db: AsyncSession, client: Client) -> str | None:
    if not client.telegram_id:
        return None
    profile = await get_client_profile(db, client.telegram_id)
    username = profile.telegram_username if profile else None
    return telegram_profile_url(client.telegram_id, username)


async def _get_master_vk_bot(db: AsyncSession, master_id: int) -> VkBot | None:
    """Активный VK-бот мастера (для VK-канала уведомлений)."""
    result = await db.execute(
        select(VkBot).where(VkBot.master_id == master_id, VkBot.status == "running")
    )
    return result.scalars().first()


async def _resolve_vk_client(
    db: AsyncSession,
    master_id: int,
    vk_user: int | str,
    vk_sig: str | None,
    auth_ts: int | None,
) -> Client:
    """Проверяет VK-подпись ссылки и возвращает карточку клиента у мастера."""
    from backend.token_utils import decrypt_token

    try:
        vk_id = int(vk_user)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid vk_user")

    vk_bot = await _get_master_vk_bot(db, master_id)
    if not vk_bot:
        raise HTTPException(status_code=403, detail="VK-бот мастера недоступен")
    token = decrypt_token(vk_bot.token)
    verify_vk_client_access(vk_id, master_id, vk_sig or "", token, auth_ts=auth_ts, require_fresh=True)

    profile = (await db.execute(
        select(VkClientProfile).where(VkClientProfile.vk_id == vk_id)
    )).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=403, detail="Сначала пройдите регистрацию в боте ВКонтакте")

    result = await db.execute(
        select(Client).where(Client.master_id == master_id, Client.vk_id == vk_id)
    )
    client = result.scalar_one_or_none()
    if client:
        client.name = profile.name
        client.phone = profile.phone
    else:
        client = Client(master_id=master_id, vk_id=vk_id, name=profile.name, phone=profile.phone)
        db.add(client)
        await db.flush()
    return client


async def _notify_master_vk(db: AsyncSession, master: Master, text: str) -> bool:
    """Шлёт уведомление мастеру в VK (если бот привязан и владелец писал сообществу)."""
    from backend.token_utils import decrypt_token

    vk_bot = await _get_master_vk_bot(db, master.id)
    if not vk_bot or not vk_bot.owner_vk_id:
        return False
    try:
        sent = await vk_api.send_message(decrypt_token(vk_bot.token), vk_bot.owner_vk_id, text)
        if not sent:
            logger.warning(
                "VK master notification rejected: master_id=%s owner_vk_id=%s",
                master.id,
                vk_bot.owner_vk_id,
            )
        return bool(sent)
    except Exception as e:
        logger.warning("VK master notification failed for master %s: %s", master.id, e)
        return False


def _vk_plain(text_html: str) -> str:
    """Грубое превращение HTML-уведомления в текст для VK (без тегов)."""
    import re as _re
    text = _re.sub(r"<a [^>]*href=\"([^\"]*)\"[^>]*>([^<]*)</a>", r"\2: \1", text_html)
    text = _re.sub(r"<[^>]+>", "", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


async def send_booking_notification(
    db: AsyncSession,
    booking: Booking,
    master: Master,
    client: Client,
    services: list[Service],
) -> dict[str, bool]:
    token = await _get_master_bot_token(db, master.id, booking.master_bot_id)

    is_vk_booking = bool(getattr(client, "vk_id", None)) and not bool(client.telegram_id)
    source_label = "ВКонтакте" if is_vk_booking else "Telegram"

    text_parts = [
        "🆕 <b>Новая запись!</b>",
        "",
        f"👤 <b>{escape(client.name)}</b>",
    ]

    if client.phone:
        text_parts.append(f"📱 {escape(client.phone)}")

    if is_vk_booking and getattr(client, "vk_id", None):
        text_parts.append(f'💬 <a href="https://vk.com/id{client.vk_id}">Написать клиенту ВКонтакте</a>')
    else:
        profile_url = await _client_profile_url(db, client)
        if profile_url:
            text_parts.append(f'💬 <a href="{profile_url}">Написать клиенту в Telegram</a>')

    text_parts.append(f"📲 <b>Запись через:</b> {source_label}")

    if services:
        text_parts.append("")
        text_parts.append("📋 <b>Услуги:</b>")
        for s in services:
            text_parts.append(f"  • {escape(s.name)} ({s.duration_minutes} мин)")
        text_parts.append(f"⏱ <b>Общая длительность:</b> {booking.duration_minutes} мин")
    elif booking.service_name:
        text_parts.append("")
        text_parts.append(f"📋 {escape(booking.service_name)} — всего {booking.duration_minutes} мин")

    text_parts.append("")
    text_parts.append(f"📅 <b>{booking.date.strftime('%d.%m.%Y')}</b>")
    text_parts.append(f"⏰ <b>{booking.time.strftime('%H:%M')}</b>")
    if services and _booking_exceeds_workday(master, booking):
        text_parts.extend([
            "",
            "⚠️ <b>Внимание:</b> клиент выбрал услуги, длительность которых выходит за пределы рабочего дня. "
            "Если принять клиента в это время неудобно, отмените запись или перенесите её в календаре.",
        ])

    if booking.comment:
        text_parts.append("")
        text_parts.append(f"📝 <b>Комментарий:</b> {escape(booking.comment)}")

    full_text = "\n".join(text_parts)

    # Уведомление мастеру — в ОБА канала: Telegram и ВКонтакте.
    master_telegram_sent = False
    if token:
        owner_chat_id = await _get_master_owner_chat_id(db, master, booking.master_bot_id)
        if owner_chat_id:
            master_telegram_sent = await _send_telegram(token, owner_chat_id, full_text)
    master_vk_sent = await _notify_master_vk(db, master, _vk_plain(full_text))

    # Уведомление клиенту — только в тот канал, откуда он записался.
    client_text = (
        f"✅ Вы записаны к {master.name}\n"
        f"📅 {booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}\n"
    )
    if services:
        client_text += f"📋 {' + '.join(s.name for s in services)}\n"
        client_text += f"⏱ Общая длительность: {booking.duration_minutes} мин\n"
    elif booking.service_name:
        client_text += f"📋 {booking.service_name}\n"
    client_text += "\nОтменить или перенести запись можно на странице онлайн-записи."

    client_sent = False
    if client.telegram_id and token:
        client_sent = await _send_telegram(token, client.telegram_id, escape(client_text))
    elif getattr(client, "vk_id", None):
        vk_bot = await _get_master_vk_bot(db, master.id)
        if vk_bot:
            from backend.token_utils import decrypt_token
            client_sent = bool(await vk_api.send_message(
                decrypt_token(vk_bot.token),
                client.vk_id,
                client_text,
            ))
            if not client_sent:
                logger.warning(
                    "VK client booking notification rejected: booking_id=%s client_vk_id=%s",
                    booking.id,
                    client.vk_id,
                )
    return {
        "master_telegram": master_telegram_sent,
        "master_vk": master_vk_sent,
        "client": client_sent,
    }


async def send_new_booking_notifications(
    db: AsyncSession,
    booking: Booking,
    master: Master,
    client: Client,
) -> dict[str, bool]:
    services = []
    if booking.service_ids:
        result = await db.execute(
            select(Service).where(
                Service.id.in_(booking.service_ids),
                Service.master_id == master.id,
            )
        )
        services = list(result.scalars().all())

    try:
        status = await send_booking_notification(db, booking, master, client, services)
        if not status["client"] or not (status["master_telegram"] or status["master_vk"]):
            logger.warning(
                "Booking notification incomplete: booking_id=%s delivery=%s",
                booking.id,
                status,
            )
        return status
    except Exception as e:
        logger.exception("Failed to send booking notification for booking_id=%s: %s", booking.id, e)
        return {"master_telegram": False, "master_vk": False, "client": False}


async def _get_verified_client(
    db: AsyncSession,
    master_id: int,
    telegram_user_id: int | str | None,
    client_sig: str | None,
    telegram_init_data: str | None,
    master_bot_id: int | None = None,
    auth_ts: int | None = None,
    vk_user: int | str | None = None,
    vk_sig: str | None = None,
) -> tuple[Master, Client]:
    """Resolve a registered client from a signed bot link or Telegram WebApp."""
    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    # VK-клиент: авторизация по подписанной ссылке бота ВКонтакте.
    if vk_user:
        client = await _resolve_vk_client(db, master_id, vk_user, vk_sig, auth_ts)
        return master, client

    bot_token = await _get_master_bot_token(db, master_id, master_bot_id)
    verified_telegram_id = None
    if telegram_init_data and bot_token:
        try:
            verified_user = await verify_telegram_init_data(telegram_init_data, bot_token)
            verified_telegram_id = verified_user.get("id")
        except HTTPException as exc:
            logger.warning(f"initData validation failed: {exc.detail}")

    if not verified_telegram_id and telegram_user_id and bot_token:
        try:
            verified_telegram_id = int(telegram_user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid telegram_user_id")
        # Ссылка из бота (client_sig) действует 10 дней; initData от Telegram свежий сам.
        verify_client_access(
            verified_telegram_id, master_id, client_sig or "", bot_token,
            auth_ts=auth_ts, require_fresh=True,
        )

    if not verified_telegram_id:
        raise HTTPException(status_code=401, detail="Откройте запись через Telegram-бота мастера")

    result = await db.execute(
        select(Client).where(
            Client.master_id == master_id,
            Client.telegram_id == verified_telegram_id,
        )
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=403, detail="Сначала пройдите регистрацию в Telegram-боте мастера")
    return master, client


def _serialize_client_booking(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "date": booking.date.isoformat(),
        "time": booking.time.strftime("%H:%M"),
        "duration_minutes": booking.duration_minutes,
        "service_name": booking.service_name,
        "service_ids": booking.service_ids or [],
        "status": booking.status,
        "comment": booking.comment,
    }


async def _apply_rescheduled_services(
    db: AsyncSession,
    master: Master,
    booking: Booking,
    requested_service_ids: list[int] | None,
) -> int:
    """Validate an updated service set and preserve snapshots for unchanged bookings."""
    if not master.use_services:
        return booking.duration_minutes
    if requested_service_ids is None:
        return booking.duration_minutes
    service_ids = list(dict.fromkeys(requested_service_ids))
    if not service_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну услугу")
    services = list((await db.execute(
        select(Service).where(
            Service.master_id == master.id,
            Service.id.in_(service_ids),
            Service.active == True,
        )
    )).scalars().all())
    if len(services) != len(service_ids):
        raise HTTPException(status_code=400, detail="Одна из выбранных услуг больше недоступна")
    by_id = {service.id: service for service in services}
    ordered = [by_id[service_id] for service_id in service_ids]
    booking.service_ids = service_ids
    booking.service_id = service_ids[0]
    booking.service_name = " + ".join(service.name for service in ordered)
    booking.service_price_total = sum(_price_to_int(service.price) for service in ordered)
    booking.duration_minutes = sum(service.duration_minutes for service in ordered)
    return booking.duration_minutes


async def _send_client_action_notification(
    db: AsyncSession,
    booking: Booking,
    master: Master,
    client: Client,
    action: str,
    comment: str = "",
    old_date: date | None = None,
    old_time: time | None = None,
) -> None:
    title = "❌ <b>Клиент отменил запись</b>" if action == "cancelled" else "🔄 <b>Клиент перенёс запись</b>"
    parts = [title, "", f"👤 <b>{escape(client.name)}</b>"]
    if client.phone:
        parts.append(f"📱 {escape(client.phone)}")
    is_vk_client = bool(getattr(client, "vk_id", None)) and not bool(client.telegram_id)
    if is_vk_client:
        parts.append(f'💬 <a href="https://vk.com/id{client.vk_id}">Написать клиенту ВКонтакте</a>')
    else:
        profile_url = await _client_profile_url(db, client)
        if profile_url:
            parts.append(f'💬 <a href="{profile_url}">Написать клиенту в Telegram</a>')
    if action == "rescheduled" and old_date and old_time:
        parts.extend([
            "",
            f"Было: {old_date.strftime('%d.%m.%Y')} в {old_time.strftime('%H:%M')}",
            f"Стало: <b>{booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}</b>",
        ])
    else:
        parts.extend(["", f"📅 {booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}"])
    if booking.service_name:
        parts.append(f"📋 {escape(booking.service_name)}")
    if comment:
        parts.extend(["", f"📝 <b>Комментарий клиента:</b> {escape(comment)}"])
    full_text = "\n".join(parts)

    # Уведомление мастеру — в ОБА канала: Telegram и ВКонтакте.
    token = await _get_master_bot_token(db, master.id, booking.master_bot_id)
    owner_chat_id = await _get_master_owner_chat_id(db, master, booking.master_bot_id)
    if token and owner_chat_id:
        await _send_telegram(token, owner_chat_id, full_text)
    await _notify_master_vk(db, master, _vk_plain(full_text))


async def _send_master_action_notification(
    db: AsyncSession,
    booking: Booking,
    master: Master,
    client: Client | None,
    action: str,
    comment: str = "",
    old_date: date | None = None,
    old_time: time | None = None,
) -> None:
    if not client:
        return

    if action == "cancelled":
        parts = [
            "❌ <b>Мастер отменил вашу запись</b>",
            "",
            f"📅 {booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}",
        ]
    else:
        parts = [
            "🔄 <b>Мастер перенёс вашу запись</b>",
            "",
            f"Было: {old_date.strftime('%d.%m.%Y')} в {old_time.strftime('%H:%M')}",
            f"Стало: <b>{booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}</b>",
        ]
    if booking.service_name:
        parts.append(f"📋 {escape(booking.service_name)}")
    if comment:
        parts.extend(["", f"📝 <b>Комментарий мастера:</b> {escape(comment)}"])
    full_text = "\n".join(parts)

    # Клиенту — в тот канал, откуда он записан: Telegram или ВКонтакте.
    if client.telegram_id:
        token = await _get_master_bot_token(db, master.id, booking.master_bot_id)
        if token:
            await _send_telegram(token, client.telegram_id, full_text)
    elif getattr(client, "vk_id", None):
        vk_bot = await _get_master_vk_bot(db, master.id)
        if vk_bot:
            from backend.token_utils import decrypt_token
            try:
                await vk_api.send_message(decrypt_token(vk_bot.token), client.vk_id, _vk_plain(full_text))
            except Exception as e:
                logger.warning("VK client action notification failed for master %s: %s", master.id, e)


def _validate_phone(phone: str) -> bool:
    if not phone:
        return False
    digits = ''.join(c for c in phone if c.isdigit())
    return len(digits) >= 10


async def _create_booking_logic_unlocked(
    data: dict,
    db: AsyncSession,
    is_admin: bool = False,
) -> ApiResponse:
    """
    Внутренняя бизнес-логика создания записи.
    Принимает распарсенный dict, возвращает ApiResponse.
    Не принимает Request — это позволяет тестировать напрямую.

    Args:
        data: распарсенное тело запроса
        db: сессия БД
        is_admin: если True — авторизованный мастер, принимает master_comment
    """
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Тело запроса должно быть объектом")

    master_id = data.get("master_id")
    date_str = data.get("date")
    time_str = data.get("time")
    service_ids = data.get("service_ids", [])
    service_names = ""
    telegram_init_data = data.get("telegram_init_data")
    master_bot_id = data.get("master_bot_id")
    telegram_user_id = data.get("telegram_user_id")
    client_sig = data.get("client_sig")
    auth_ts = data.get("auth_ts")
    def clean_text(key: str, max_length: int) -> str:
        value = data.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{key} должен быть текстом")
        value = value.strip()
        if len(value) > max_length:
            raise HTTPException(
                status_code=400,
                detail=f"{key} не должен превышать {max_length} символов",
            )
        return value

    client_name = clean_text("client_name", 255)
    client_phone = clean_text("client_phone", 50)
    comment = clean_text("comment", 500)
    master_comment = clean_text("master_comment", 500) if is_admin else ""
    session_id = data.get("session_id") or data.get("telegram_init_data") or ""

    # Публичный endpoint не принимает master_comment
    if not is_admin and data.get("master_comment"):
        raise HTTPException(status_code=400, detail="master_comment not allowed on public endpoint")

    if not master_id:
        raise HTTPException(status_code=400, detail="master_id required")
    if not date_str or not time_str:
        raise HTTPException(status_code=400, detail="date and time required")
    if not isinstance(date_str, str) or not isinstance(time_str, str):
        raise HTTPException(status_code=400, detail="date and time must be strings")
    if not isinstance(service_ids, list) or any(
        not isinstance(service_id, int) for service_id in service_ids
    ):
        raise HTTPException(status_code=400, detail="service_ids must be a list of integers")

    try:
        booking_date = dt.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    try:
        booking_time = dt.strptime(time_str, "%H:%M:%S").time()
    except (TypeError, ValueError):
        try:
            booking_time = dt.strptime(time_str, "%H:%M").time()
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM or HH:MM:SS")

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    is_demo = master.is_demo or master_id == 999
    if master.use_services and not service_ids and not is_demo:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну услугу")

    total_duration = master.interval_minutes or 60
    services = []
    service_price_total = None
    if service_ids:
        result = await db.execute(
            select(Service).where(
                Service.id.in_(service_ids),
                Service.master_id == master_id,
                Service.active == True
            )
        )
        services = list(result.scalars().all())
        if len(services) != len(set(service_ids)):
            raise HTTPException(status_code=400, detail="Invalid service IDs")
        total_duration = sum(s.duration_minutes for s in services)
        service_names = " + ".join(s.name for s in services)
        service_price_total = sum(_price_to_int(s.price) for s in services)

    end_time = _validate_schedule_interval(
        master,
        booking_date,
        booking_time,
        total_duration,
    )

    # Проверки занятости слота (blocked/booking/hold) перенесены НИЖЕ — после
    # авторизации клиента и захвата advisory lock. Иначе неавторизованный запрос
    # по коду ответа (409 vs 401) мог прощупывать занятость чужого расписания.

    if is_demo:
        logger.info(f"[DEMO] Booking simulated for {client_name or 'unknown'}")
        return ApiResponse(
            success=True,
            data={
                "booking_id": 999999,
                "client_name": client_name or "Demo Client",
                "date": date_str,
                "time": time_str,
                "services": service_names,
                "demo_mode": True,
            },
        )

    # Админский сценарий: создаём/находим клиента по имени+телефону внутри master_id
    if is_admin:
        if not client_name:
            raise HTTPException(status_code=400, detail="client_name required for admin booking")

        # Ищем существующую карточку только по НЕПУСТОМУ телефону. Раньше при пустом
        # телефоне запрос Client.phone == "" мог случайно склеить разных клиентов
        # без номера; теперь без телефона просто заводим новую карточку.
        client = None
        if client_phone:
            result = await db.execute(
                select(Client).where(
                    Client.master_id == master_id,
                    Client.phone == client_phone,
                )
            )
            client = result.scalar_one_or_none()

        if not client:
            client = Client(
                master_id=master_id,
                telegram_id=None,
                name=client_name,
                phone=client_phone or None,
            )
            db.add(client)
            await db.flush()
        else:
            if client.name != client_name:
                client.name = client_name
            if client_phone and not client.phone:
                client.phone = client_phone

    elif data.get("vk_user"):
        # Клиент пришёл из бота ВКонтакте — авторизация по VK ID.
        client = await _resolve_vk_client(
            db, master_id, data.get("vk_user"), data.get("vk_sig"), auth_ts
        )

    else:
        verified_telegram_id = None
        bot_token = await _get_master_bot_token(db, master_id, master_bot_id)

        if telegram_init_data:
            if bot_token:
                try:
                    verified_user = await verify_telegram_init_data(telegram_init_data, bot_token)
                    verified_telegram_id = verified_user.get("id")
                except HTTPException as e:
                    logger.warning(f"initData validation failed: {e.detail}")
                    verified_telegram_id = None

        if not verified_telegram_id and telegram_user_id and bot_token:
            try:
                verified_telegram_id = int(telegram_user_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid telegram_user_id")
            verify_client_access(
                verified_telegram_id, master_id, client_sig or "", bot_token,
                auth_ts=auth_ts, require_fresh=True,
            )

        if not verified_telegram_id:
            raise HTTPException(
                status_code=401,
                detail="Сначала откройте Telegram-бота мастера и пройдите регистрацию"
            )

        profile = await get_client_profile(db, verified_telegram_id)
        if not profile:
            raise HTTPException(
                status_code=403,
                detail="Сначала поделитесь номером телефона и укажите ФИ в Telegram-боте мастера"
            )
        client = await ensure_master_client(db, master_id, profile)

    slot_hash = booking_time.hour * 10000 + booking_time.minute * 100 + total_duration
    if not await acquire_slot_lock(db, master_id, booking_date, slot_hash):
        raise HTTPException(status_code=409, detail="Slot temporarily locked, try again")

    # Заблокированное мастером время — проверяем внутри advisory lock, после авторизации.
    blocked_result = await db.execute(
        select(BlockedTime).where(
            BlockedTime.master_id == master_id,
            BlockedTime.date == booking_date,
        )
    )
    for blocked in blocked_result.scalars().all():
        if time_overlaps(booking_time, end_time, blocked.start_time, blocked.end_time):
            raise HTTPException(status_code=409, detail=f"Time blocked: {blocked.reason or 'by master'}")

    # Повторная проверка пересечений — внутри advisory lock
    bookings_result = await db.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.date == booking_date,
            Booking.status.in_(["upcoming", "confirmed"]),
        )
    )
    for b in bookings_result.scalars().all():
        b_time = b.time if isinstance(b.time, time) else dt.strptime(str(b.time), "%H:%M:%S").time()
        b_end_mins = time_to_minutes(b_time) + b.duration_minutes
        b_end = time(b_end_mins // 60, b_end_mins % 60) if b_end_mins < 24 * 60 else END_OF_DAY
        if time_overlaps(booking_time, end_time, b_time, b_end):
            raise HTTPException(status_code=409, detail="Time already booked")

    # Проверка SlotHold — всегда, не только если передан session_id.
    # Если session_id пустой — любой пересекающийся активный hold считается чужим.
    hold_result = await db.execute(
        select(SlotHold).where(
            SlotHold.master_id == master_id,
            SlotHold.date == booking_date,
            SlotHold.expires_at > dt.utcnow(),
        )
    )
    for h in hold_result.scalars().all():
        h_time = h.time if isinstance(h.time, time) else dt.strptime(str(h.time), "%H:%M:%S").time()
        h_end_mins = time_to_minutes(h_time) + (h.duration_minutes or 60)
        h_end = time(h_end_mins // 60, h_end_mins % 60) if h_end_mins < 24 * 60 else END_OF_DAY
        if time_overlaps(booking_time, end_time, h_time, h_end):
            if h.session_id == session_id and session_id:
                # Свой hold — пропускаем
                continue
            raise HTTPException(status_code=409, detail="Slot temporarily held by another client")

    ends_at_mins = time_to_minutes(booking_time) + total_duration
    ends_at = time(ends_at_mins // 60, ends_at_mins % 60) if ends_at_mins < 24 * 60 else END_OF_DAY

    booking = Booking(
        master_id=master_id,
        master_bot_id=master_bot_id,
        client_id=client.id,
        date=booking_date,
        time=booking_time,
        duration_minutes=total_duration,
        ends_at=ends_at,
        service_ids=service_ids,
        service_id=service_ids[0] if service_ids else None,
        service_name=service_names or None,
        service_price_total=service_price_total,
        status="upcoming",
        comment=comment or None,
        master_comment=master_comment or None,
    )
    db.add(booking)
    await db.flush()
    db.add(BookingStatusHistory(
        booking_id=booking.id,
        new_status="upcoming",
        changed_by="master" if is_admin else "client",
    ))

    await db.commit()
    await db.refresh(booking)

    logger.info(f"[BOOKING] Created booking {booking.id} for client {client.name}")

    notification_status = await send_new_booking_notifications(db, booking, master, client)

    return ApiResponse(
        success=True,
        data={
            "id": booking.id,
            "client_name": client.name,
            "date": date_str,
            "time": time_str,
            "services": service_names,
            "notified": bool(
                notification_status["client"]
                and (notification_status["master_telegram"] or notification_status["master_vk"])
            ),
            "notification_status": notification_status,
        },
    )


@asynccontextmanager
async def _booking_creation_guard(db: AsyncSession):
    """Serialize SQLite writes so concurrent requests cannot double-book a slot."""
    bind = db.get_bind()
    if bind and bind.dialect.name == "sqlite":
        async with _sqlite_booking_lock:
            yield
        return
    yield


async def _create_booking_logic(
    data: dict,
    db: AsyncSession,
    is_admin: bool = False,
) -> ApiResponse:
    async with _booking_creation_guard(db):
        return await _create_booking_logic_unlocked(data, db, is_admin=is_admin)


@router.post("", response_model=ApiResponse)
async def create_booking(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Публичный endpoint для создания записи клиентом.
    Demo mode: запись не сохраняется, возвращается success с demo_mode=True
    Real mode: требуется зарегистрированный Telegram-клиент из подписанной ссылки бота
    Не принимает master_comment.
    """
    from backend.rate_limiter import client_ip_from_request
    client_ip = client_ip_from_request(request)
    if not await rate_limiter.check(client_ip):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    return await _create_booking_logic(body, db, is_admin=False)


async def _get_owned_client_booking(
    db: AsyncSession,
    booking_id: int,
    master_id: int,
    telegram_user_id: int | str | None,
    client_sig: str | None,
    telegram_init_data: str | None,
    master_bot_id: int | None = None,
    auth_ts: int | None = None,
    vk_user: int | str | None = None,
    vk_sig: str | None = None,
) -> tuple[Booking, Master, Client]:
    master, client = await _get_verified_client(
        db, master_id, telegram_user_id, client_sig, telegram_init_data, master_bot_id, auth_ts,
        vk_user=vk_user, vk_sig=vk_sig,
    )
    booking = await db.get(Booking, booking_id)
    if not booking or booking.master_id != master.id or booking.client_id != client.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status not in ("upcoming", "confirmed"):
        raise HTTPException(status_code=400, detail="Этой записью уже нельзя управлять")
    tz = _master_tz(master)
    if dt.combine(booking.date, booking.time, tzinfo=tz) < _master_now(master):
        raise HTTPException(status_code=400, detail="Прошедшую запись нельзя изменить")
    return booking, master, client


@router.get("/client", response_model=ApiResponse)
async def get_client_bookings(
    master_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    telegram_user_id: Optional[int] = Query(None),
    client_sig: Optional[str] = Query(None),
    telegram_init_data: Optional[str] = Query(None),
    master_bot_id: Optional[int] = Query(None),
    auth_ts: Optional[int] = Query(None),
    vk_user: Optional[int] = Query(None),
    vk_sig: Optional[str] = Query(None),
):
    """Return future bookings belonging to the authenticated client (Telegram or VK)."""
    master_bot_id = master_bot_id if isinstance(master_bot_id, int) else None
    vk_user = vk_user if isinstance(vk_user, (int, str)) else None
    vk_sig = vk_sig if isinstance(vk_sig, str) else None
    master, client = await _get_verified_client(
        db, master_id, telegram_user_id, client_sig, telegram_init_data, master_bot_id, auth_ts,
        vk_user=vk_user, vk_sig=vk_sig,
    )
    tz = _master_tz(master)
    now = _master_now(master)
    result = await db.execute(
        select(Booking)
        .where(
            Booking.master_id == master_id,
            Booking.client_id == client.id,
            Booking.status.in_(["upcoming", "confirmed"]),
            Booking.date >= now.date(),
        )
        .order_by(Booking.date, Booking.time)
    )
    bookings = [
        booking
        for booking in result.scalars().all()
        if dt.combine(booking.date, booking.time, tzinfo=tz) >= now
    ]
    return ApiResponse(success=True, data={"bookings": [_serialize_client_booking(booking) for booking in bookings]})


@router.post("/client/{booking_id}/cancel", response_model=ApiResponse)
async def client_cancel_booking(
    booking_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Тело запроса должно быть объектом")
    comment = (body.get("comment") or "").strip()
    if len(comment) > 500:
        raise HTTPException(status_code=400, detail="Комментарий не должен превышать 500 символов")
    booking, master, client = await _get_owned_client_booking(
        db,
        booking_id,
        body.get("master_id"),
        body.get("telegram_user_id"),
        body.get("client_sig"),
        body.get("telegram_init_data"),
        body.get("master_bot_id"),
        body.get("auth_ts"),
        vk_user=body.get("vk_user"),
        vk_sig=body.get("vk_sig"),
    )
    previous_status = booking.status
    booking.status = "cancelled"
    booking.cancelled_at = dt.utcnow()
    db.add(BookingStatusHistory(
        booking_id=booking.id,
        old_status=previous_status,
        new_status="cancelled",
        changed_by="client",
        reason=comment or None,
    ))
    await db.commit()
    await _send_client_action_notification(db, booking, master, client, "cancelled", comment)
    return ApiResponse(success=True, data={"id": booking.id, "status": booking.status})


@router.post("/client/{booking_id}/reschedule", response_model=ApiResponse)
async def client_reschedule_booking(
    booking_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    async with _booking_creation_guard(db):
        return await _client_reschedule_booking_unlocked(booking_id, request, db)


async def _client_reschedule_booking_unlocked(
    booking_id: int,
    request: Request,
    db: AsyncSession,
):
    body = await request.json()
    comment = (body.get("comment") or "").strip()
    if len(comment) > 500:
        raise HTTPException(status_code=400, detail="Комментарий не должен превышать 500 символов")
    booking, master, client = await _get_owned_client_booking(
        db,
        booking_id,
        body.get("master_id"),
        body.get("telegram_user_id"),
        body.get("client_sig"),
        body.get("telegram_init_data"),
        body.get("master_bot_id"),
        body.get("auth_ts"),
        vk_user=body.get("vk_user"),
        vk_sig=body.get("vk_sig"),
    )
    try:
        new_date = dt.strptime(body.get("new_date") or "", "%Y-%m-%d").date()
        new_time = dt.strptime(body.get("new_time") or "", "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Выберите корректные дату и время")

    if new_date == booking.date and new_time == booking.time and not body.get("service_ids"):
        raise HTTPException(status_code=400, detail="Это то же самое время записи. Выберите другую дату или время.")

    duration = await _apply_rescheduled_services(db, master, booking, body.get("service_ids"))
    new_end = _validate_schedule_interval(master, new_date, new_time, duration)
    if not await acquire_slot_lock(db, master.id, new_date, 0):
        raise HTTPException(status_code=409, detail="Слот временно занят, попробуйте ещё раз")

    blocked_result = await db.execute(
        select(BlockedTime).where(BlockedTime.master_id == master.id, BlockedTime.date == new_date)
    )
    for blocked in blocked_result.scalars().all():
        if time_overlaps(new_time, new_end, blocked.start_time, blocked.end_time):
            raise HTTPException(status_code=409, detail="Новое время заблокировано мастером")

    bookings_result = await db.execute(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.date == new_date,
            Booking.status.in_(["upcoming", "confirmed"]),
            Booking.id != booking.id,
        )
    )
    for other in bookings_result.scalars().all():
        other_end = other.ends_at or interval_end(other.time, other.duration_minutes)
        if time_overlaps(new_time, new_end, other.time, other_end):
            raise HTTPException(status_code=409, detail="Это время уже занято")

    hold_result = await db.execute(
        select(SlotHold).where(
            SlotHold.master_id == master.id,
            SlotHold.date == new_date,
            SlotHold.expires_at > dt.utcnow(),
        )
    )
    for hold in hold_result.scalars().all():
        if time_overlaps(new_time, new_end, hold.time, interval_end(hold.time, hold.duration_minutes or 60)):
            raise HTTPException(status_code=409, detail="Это время временно удерживается другим клиентом")

    old_date, old_time = booking.date, booking.time
    booking.date = new_date
    booking.time = new_time
    booking.ends_at = new_end
    db.add(BookingStatusHistory(
        booking_id=booking.id,
        old_status=booking.status,
        new_status=booking.status,
        changed_by="client",
        reason=f"Перенос с {old_date} {old_time.strftime('%H:%M')} на {new_date} {new_time.strftime('%H:%M')}. {comment}".strip(),
    ))
    await db.commit()
    await db.refresh(booking)
    await _send_client_action_notification(
        db, booking, master, client, "rescheduled", comment, old_date=old_date, old_time=old_time
    )
    return ApiResponse(success=True, data=_serialize_client_booking(booking))


# =============================================================================
# Admin endpoints — авторизованный мастер создаёт запись вручную
# =============================================================================

@router.post("/admin", response_model=ApiResponse)
async def admin_create_booking(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    """
    Ручное создание записи мастером.
    Принимает auth через verify_master_access (user/sig из URL).
    master_id берётся из авторизации, а не из body.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Принудительно подставляем master_id из авторизации
    body["master_id"] = master.id

    return await _create_booking_logic(body, db, is_admin=True)


@router.delete("/{booking_id}", response_model=ApiResponse)
async def cancel_booking(
    booking_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.master_id != master.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Already cancelled")

    try:
        body = await request.json()
        reason = body.get("reason", "")
        cancelled_by = body.get("cancelled_by", "master")
    except Exception:
        reason = ""
        cancelled_by = "master"

    previous_status = booking.status
    booking.status = "cancelled"
    booking.cancelled_at = dt.utcnow()
    client = await db.get(Client, booking.client_id)

    history = BookingStatusHistory(
        booking_id=booking_id,
        old_status=previous_status,
        new_status="cancelled",
        changed_by=cancelled_by,
        reason=reason,
    )
    db.add(history)

    await db.commit()
    await _send_master_action_notification(db, booking, master, client, "cancelled", reason)

    logger.info(f"[BOOKING] Cancelled booking {booking_id}: {reason}")

    return ApiResponse(success=True, data={"id": booking_id, "status": "cancelled"})


@router.get("/{booking_id}", response_model=ApiResponse)
async def get_booking(
    booking_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    booking = await db.get(Booking, booking_id)
    if not booking or booking.master_id != master.id:
        raise HTTPException(status_code=404, detail="Booking not found")

    client = await db.get(Client, booking.client_id)

    return ApiResponse(
        success=True,
        data={
            "id": booking.id,
            "master_id": booking.master_id,
            "client": {
                "id": client.id,
                "name": client.name,
                "phone": client.phone,
                "telegram_id": client.telegram_id,
            },
            "date": booking.date.isoformat(),
            "time": str(booking.time),
            "duration_minutes": booking.duration_minutes,
            "service_ids": booking.service_ids,
            "service_name": booking.service_name,
            "status": booking.status,
            "comment": booking.comment,
            "master_comment": booking.master_comment,
        },
    )


@router.post("/{booking_id}/reschedule", response_model=ApiResponse)
async def reschedule_booking(
    booking_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    async with _booking_creation_guard(db):
        return await _reschedule_booking_unlocked(booking_id, request, db, master)


async def _reschedule_booking_unlocked(
    booking_id: int,
    request: Request,
    db: AsyncSession,
    master: Master,
):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.master_id != master.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot reschedule cancelled booking")

    try:
        body = await request.json()
        new_date_str = body.get("new_date") or request.query_params.get("new_date")
        new_time_str = body.get("new_time") or request.query_params.get("new_time")
        comment = body.get("comment", "")
        service_ids = body.get("service_ids")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not new_date_str or not new_time_str:
        raise HTTPException(status_code=400, detail="new_date and new_time required")

    try:
        new_date = dt.strptime(new_date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    try:
        new_time = dt.strptime(new_time_str, "%H:%M:%S").time()
    except ValueError:
        try:
            new_time = dt.strptime(new_time_str, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid time format")

    if new_date == booking.date and new_time == booking.time and not service_ids:
        raise HTTPException(status_code=400, detail="Это то же самое время записи. Выберите другую дату или время.")

    duration = await _apply_rescheduled_services(db, master, booking, service_ids)
    new_end = _validate_schedule_interval(master, new_date, new_time, duration)

    if not await acquire_slot_lock(db, master.id, new_date, 0):
        raise HTTPException(status_code=409, detail="Slot temporarily locked, try again")

    blocked_result = await db.execute(
        select(BlockedTime).where(
            BlockedTime.master_id == master.id,
            BlockedTime.date == new_date,
        )
    )
    for blocked in blocked_result.scalars().all():
        if time_overlaps(new_time, new_end, blocked.start_time, blocked.end_time):
            raise HTTPException(status_code=409, detail="New time blocked")

    bookings_result = await db.execute(
        select(Booking).where(
            Booking.master_id == master.id,
            Booking.date == new_date,
            Booking.status.in_(["upcoming", "confirmed"]),
            Booking.id != booking_id,
        )
    )
    for b in bookings_result.scalars().all():
        b_time = b.time if isinstance(b.time, time) else dt.strptime(str(b.time), "%H:%M:%S").time()
        b_end_mins = time_to_minutes(b_time) + b.duration_minutes
        b_end = time(b_end_mins // 60, b_end_mins % 60) if b_end_mins < 24 * 60 else END_OF_DAY
        if time_overlaps(new_time, new_end, b_time, b_end):
            raise HTTPException(status_code=409, detail="New time conflicts with another booking")

    hold_result = await db.execute(
        select(SlotHold).where(
            SlotHold.master_id == master.id,
            SlotHold.date == new_date,
            SlotHold.expires_at > dt.utcnow(),
        )
    )
    for hold in hold_result.scalars().all():
        hold_time = hold.time if isinstance(hold.time, time) else dt.strptime(str(hold.time), "%H:%M:%S").time()
        hold_end = interval_end(hold_time, hold.duration_minutes or 60)
        if time_overlaps(new_time, new_end, hold_time, hold_end):
            raise HTTPException(status_code=409, detail="New time is temporarily held")

    old_date = booking.date
    old_time = booking.time

    history = BookingStatusHistory(
        booking_id=booking_id,
        old_status=booking.status,
        new_status=booking.status,
        changed_by="master",
        reason=f"Rescheduled from {old_date} {old_time} to {new_date} {new_time}. {comment}".strip(),
    )
    db.add(history)

    booking.date = new_date
    booking.time = new_time
    booking.ends_at = new_end
    if comment:
        booking.master_comment = (booking.master_comment or "") + f"\nПеренос: {comment}"

    await db.commit()
    await db.refresh(booking)
    client = await db.get(Client, booking.client_id)
    await _send_master_action_notification(
        db, booking, master, client, "rescheduled", comment, old_date=old_date, old_time=old_time
    )

    logger.info(f"[BOOKING] Rescheduled booking {booking_id}: {old_date} {old_time} -> {new_date} {new_time}")

    return ApiResponse(
        success=True,
        data={
            "id": booking_id,
            "date": new_date.isoformat(),
            "time": new_time_str,
            "status": booking.status,
        },
    )


@router.delete("/{booking_id}/hard", response_model=ApiResponse)
async def hard_delete_booking(
    booking_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.master_id != master.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    # Жёсткое удаление — только для уже отменённых записей. Иначе активную запись
    # можно было бесследно стереть, и клиент остался бы с уверенностью, что записан.
    if booking.status not in ("cancelled", "completed", "no_show"):
        raise HTTPException(status_code=400, detail="Сначала отмените запись, потом её можно удалить.")

    history_result = await db.execute(
        select(BookingStatusHistory).where(BookingStatusHistory.booking_id == booking_id)
    )
    for history in history_result.scalars().all():
        await db.delete(history)
    await db.delete(booking)
    await db.commit()

    logger.info(f"[BOOKING] Hard deleted booking {booking_id}")

    return ApiResponse(success=True, data={"id": booking_id, "deleted": True})
