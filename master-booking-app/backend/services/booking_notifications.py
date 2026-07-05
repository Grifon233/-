"""Scheduled client reminders and weekly reports for masters."""
import asyncio
import logging
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.database import Booking, Client, Master, MasterBot, SlotHold, async_session_maker
from backend.routers.booking import _get_master_bot_token, _get_master_vk_bot, _send_telegram, _vk_plain
from backend.timezones import DEFAULT_TIMEZONE
from backend.token_utils import decrypt_token
from backend.vk import api as vk_api

logger = logging.getLogger(__name__)


def _local_now(master: Master, now_utc: datetime) -> datetime:
    return now_utc.astimezone(ZoneInfo(master.timezone or DEFAULT_TIMEZONE))


def _time_reached(local_now: datetime, configured: str) -> bool:
    try:
        target = time.fromisoformat(configured)
    except ValueError:
        target = time(18, 0)
    return local_now.time() >= target


def _reminder_cutoff(local_now: datetime, configured: str) -> datetime:
    try:
        target = time.fromisoformat(configured)
    except ValueError:
        target = time(18, 0)
    return datetime.combine(local_now.date(), target, tzinfo=local_now.tzinfo)


async def process_due_client_reminders(now_utc: datetime | None = None) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    sent = 0
    async with async_session_maker() as db:
        masters = (await db.execute(select(Master).where(Master.notify_reminders == True))).scalars().all()
        for master in masters:
            local_now = _local_now(master, now_utc)
            if not _time_reached(local_now, master.reminder_time or "18:00"):
                continue
            rows = (await db.execute(
                select(Booking, Client).join(Client).where(
                    Booking.master_id == master.id,
                    Booking.date == local_now.date() + timedelta(days=1),
                    Booking.status.in_(["upcoming", "confirmed"]),
                    Booking.reminder_sent_at.is_(None),
                )
            )).all()
            for booking, client in rows:
                # Раньше запись, созданная позже времени напоминания (например,
                # клиент записался вечером на завтра), напоминание не получала вовсе.
                # Теперь такому клиенту напоминание уходит при ближайшем проходе цикла.
                is_vk_client = bool(getattr(client, "vk_id", None)) and not bool(client.telegram_id)
                if not client.telegram_id and not is_vk_client:
                    continue
                parts = [
                    "⏰ <b>Напоминание о записи</b>",
                    "",
                    f"Завтра вы записаны к {escape(master.name)}.",
                    f"📅 {booking.date.strftime('%d.%m.%Y')} в {booking.time.strftime('%H:%M')}",
                ]
                if booking.service_name:
                    parts.append(f"📋 {escape(booking.service_name)}")
                parts.append(f"⏱ Длительность: {booking.duration_minutes} мин")
                parts.extend([
                    "",
                    "Если вы не сможете присутствовать, отмените или перенесите запись.",
                ])
                message_text = "\n".join(parts)

                # Клиенту — в тот канал, откуда он записан: Telegram или ВКонтакте.
                delivered = False
                if client.telegram_id:
                    token = await _get_master_bot_token(db, master.id, booking.master_bot_id)
                    if token and await _send_telegram(token, client.telegram_id, message_text):
                        delivered = True
                elif is_vk_client:
                    vk_bot = await _get_master_vk_bot(db, master.id)
                    if vk_bot:
                        try:
                            delivered = await vk_api.send_message(
                                decrypt_token(vk_bot.token), client.vk_id, _vk_plain(message_text)
                            )
                        except Exception as exc:
                            logger.warning("VK client reminder failed for master %s: %s", master.id, exc)
                if delivered:
                    booking.reminder_sent_at = datetime.utcnow()
                    sent += 1
        await db.commit()
    return sent


def _weekly_report_text(
    master: Master,
    rows: list[tuple[Booking, Client]],
    week_start: date,
    prior_client_ids: set[int] | None = None,
) -> str:
    active = [(booking, client) for booking, client in rows if booking.status != "cancelled"]
    cancelled = len(rows) - len(active)
    client_ids = [client.id for _, client in active]
    unique_clients = set(client_ids)
    repeat_visits = len(client_ids) - len(unique_clients)
    prior_client_ids = prior_client_ids or set()
    new_clients = len(unique_clients - prior_client_ids)
    minutes = sum(booking.duration_minutes or 0 for booking, _ in active)
    revenue = sum(booking.service_price_total or 0 for booking, _ in active)
    services = Counter(
        name.strip()
        for booking, _ in active
        for name in (booking.service_name or "").split(" + ")
        if name.strip()
    )
    days = Counter(booking.date.strftime("%d.%m") for booking, _ in active)
    top_service = services.most_common(1)[0][0] if services else "нет данных"
    busiest_day = days.most_common(1)[0][0] if days else "нет данных"
    average_minutes = round(minutes / len(active)) if active else 0
    vk_count = sum(1 for _, client in active if getattr(client, "vk_id", None))
    tg_count = sum(1 for _, client in active if client.telegram_id and not getattr(client, "vk_id", None))
    lines = [
        "📊 <b>Отчёт за неделю</b>",
        f"{week_start.strftime('%d.%m.%Y')}–{(week_start + timedelta(days=6)).strftime('%d.%m.%Y')}",
        "",
        f"Записей: <b>{len(active)}</b>",
        f"В Telegram к вам записалось: <b>{tg_count}</b>",
        f"В ВКонтакте к вам записалось: <b>{vk_count}</b>",
        f"Новых клиентов: <b>{new_clients}</b>",
        f"Повторных визитов: <b>{repeat_visits}</b>",
        f"Отмен: <b>{cancelled}</b>",
        f"Отработано времени: <b>{minutes // 60} ч {minutes % 60} мин</b>",
        f"Средняя длительность визита: <b>{average_minutes} мин</b>",
        f"Самый загруженный день: <b>{busiest_day}</b>",
    ]
    if master.use_services:
        lines.extend([
            f"Самая популярная услуга: <b>{escape(top_service)}</b>",
            f"Доход по указанным ценам: <b>{revenue} ₽</b>",
        ])
    return "\n".join(lines)


async def process_due_weekly_reports(now_utc: datetime | None = None) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    sent = 0
    async with async_session_maker() as db:
        masters = (await db.execute(select(Master).where(Master.weekly_report_enabled == True))).scalars().all()
        for master in masters:
            local_now = _local_now(master, now_utc)
            if local_now.weekday() != 6 or local_now.time() < time(18, 0):
                continue
            if master.weekly_report_sent_at:
                previous = master.weekly_report_sent_at.replace(tzinfo=timezone.utc).astimezone(local_now.tzinfo)
                if previous.date() == local_now.date():
                    continue
            week_start = local_now.date() - timedelta(days=6)
            rows = (await db.execute(
                select(Booking, Client).join(Client).where(
                    Booking.master_id == master.id,
                    Booking.date >= week_start,
                    Booking.date <= local_now.date(),
                )
            )).all()
            rows = [
                (booking, client)
                for booking, client in rows
                if (
                    booking.status == "cancelled"
                    or booking.date < local_now.date()
                    or (booking.date == local_now.date() and booking.time <= local_now.time())
                )
            ]
            prior_client_ids = set((await db.execute(
                select(Booking.client_id).where(
                    Booking.master_id == master.id,
                    Booking.date < week_start,
                    Booking.status != "cancelled",
                ).distinct()
            )).scalars().all())
            token = await _get_master_bot_token(db, master.id)
            owner_chat_id = master.telegram_id
            if not owner_chat_id:
                owner_chat_id = (await db.execute(
                    select(MasterBot.master_telegram_id).where(
                        MasterBot.master_id == master.id,
                        MasterBot.status == "running",
                    )
                )).scalars().first()
            if token and owner_chat_id and await _send_telegram(
                token, owner_chat_id, _weekly_report_text(master, rows, week_start, prior_client_ids)
            ):
                master.weekly_report_sent_at = datetime.utcnow()
                sent += 1
        await db.commit()
    return sent


async def cleanup_expired_slot_holds() -> int:
    async with async_session_maker() as db:
        result = await db.execute(delete(SlotHold).where(SlotHold.expires_at <= datetime.utcnow()))
        await db.commit()
        return result.rowcount or 0


async def run_booking_notification_loop() -> None:
    while True:
        try:
            await process_due_client_reminders()
            await process_due_weekly_reports()
            await cleanup_expired_slot_holds()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled booking notification cycle failed")
        await asyncio.sleep(60)
