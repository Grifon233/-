import logging
from datetime import date as date_type, time as time_type, datetime, timedelta
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import BlockedTime, Booking, Client, MasterBot, SlotHold, VkBot, get_db
from backend.media_storage import normalize_media_reference
from backend.rate_limiter import client_ip_from_request, rate_limiter
from backend.schemas.schemas import ApiResponse
from backend.time_utils import END_OF_DAY, time_to_minutes, time_overlaps, interval_end, is_schedule_date_excluded, resolve_day_schedule
from backend.token_utils import decrypt_token
from backend.vk.auth import verify_vk_client_access

router = APIRouter( tags=["masters"])
logger = logging.getLogger(__name__)

async def _require_running_bot(
    db: AsyncSession,
    master_id: int,
    bot_id: int | None = None,
    vk_bot_id: int | None = None,
    vk_user: int | None = None,
    vk_sig: str | None = None,
    auth_ts: int | None = None,
) -> None:
    from backend.database import Master

    master = await db.get(Master, master_id)
    bot = await db.get(MasterBot, bot_id) if bot_id else None
    vk_bot = await db.get(VkBot, vk_bot_id) if vk_bot_id else None
    linked = bool(master) and (
        bool(bot)
        and bot.status == "running"
        and (
            bot.master_id == master.id
            or (bot.master_id is None and bot.master_telegram_id == master.telegram_id)
        )
        or bool(vk_bot) and vk_bot.master_id == master.id and vk_bot.status == "running"
    )
    if not linked and master and vk_user and vk_sig:
        vk_bots = (await db.execute(
            select(VkBot).where(
                VkBot.master_id == master.id,
                VkBot.status == "running",
            )
        )).scalars().all()
        for candidate in vk_bots:
            try:
                verify_vk_client_access(
                    vk_user,
                    master_id,
                    vk_sig,
                    decrypt_token(candidate.token),
                    auth_ts=auth_ts,
                    require_fresh=True,
                )
                linked = True
                break
            except HTTPException:
                continue
    if not linked and master and vk_user:
        # Данные профиля, услуг и свободных слотов являются публичными.
        # Для старых VK-клавиатур без vk_bot_id достаточно убедиться, что у
        # этого профиля по-прежнему работает хотя бы один VK-бот. Создание и
        # изменение записи ниже всё равно требуют корректную VK-подпись.
        linked = bool((await db.execute(
            select(VkBot.id).where(
                VkBot.master_id == master.id,
                VkBot.status == "running",
            ).limit(1)
        )).scalar_one_or_none())
    if not linked:
        raise HTTPException(status_code=403, detail="Ссылка записи недоступна. В боте ещё раз нажмите /start и получите актуальную ссылку")

@router.get("/{master_id:int}", response_model=ApiResponse)
async def get_public_master(
    master_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    bot_id: int | None = None,
    vk_bot_id: int | None = None,
    vk_user: int | None = None,
    vk_sig: str | None = None,
    auth_ts: int | None = None,
):
    from backend.database import Master, Service

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    await _require_running_bot(db, master_id, bot_id, vk_bot_id, vk_user, vk_sig, auth_ts)

    return ApiResponse(success=True, data={
        "id": master.id,
        "name": master.name,
        "avatar_url": normalize_media_reference(master.avatar_url),
        "telegram_username": master.telegram_username,
        "use_services": master.use_services,
        "interval_minutes": master.interval_minutes,
        "schedule": master.schedule_json,
        "subscription_required": master.subscription_required or False,
        "subscription_text": master.subscription_text,
    })

@router.get("/{master_id:int}/services", response_model=ApiResponse)
async def get_master_services(
    master_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    bot_id: int | None = None,
    vk_bot_id: int | None = None,
    vk_user: int | None = None,
    vk_sig: str | None = None,
    auth_ts: int | None = None,
):
    from backend.database import Master, Service

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    await _require_running_bot(db, master_id, bot_id, vk_bot_id, vk_user, vk_sig, auth_ts)

    result = await db.execute(
        select(Service).where(Service.master_id == master_id, Service.active == True).order_by(Service.sort_order)
    )
    services = result.scalars().all()

    return ApiResponse(
        success=True,
        data={
            "use_services": master.use_services,
            "services": [
                {
                    "id": s.id,
                    "name": s.name,
                    "price": s.price,
                    "duration_minutes": s.duration_minutes,
                    "active": s.active,
                }
                for s in services
            ],
        },
    )


@router.get("/{master_id:int}/slots", response_model=ApiResponse)
async def get_slots(
    master_id: int,
    date: date_type,
    duration: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    bot_id: int | None = None,
    vk_bot_id: int | None = None,
    vk_user: int | None = None,
    vk_sig: str | None = None,
    auth_ts: int | None = None,
    service_ids: Optional[str] = None,
    exclude_booking_id: Optional[int] = None,
    request: Request = None,
):
    from backend.database import Master, Service

    # Предохранитель от некорректных клиентских запросов: слот не должен
    # раскручивать тяжёлый расчёт из-за странной длительности или шага.
    if duration < 15 or duration > 480:
        raise HTTPException(status_code=400, detail="Duration must be between 15 and 480 minutes")
    if request and not await rate_limiter.check(f"public-slots:{client_ip_from_request(request)}"):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте через минуту")

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    await _require_running_bot(db, master_id, bot_id, vk_bot_id, vk_user, vk_sig, auth_ts)
    try:
        local_now = datetime.now(ZoneInfo(master.timezone or "Europe/Moscow"))
    except Exception:
        local_now = datetime.now(ZoneInfo("Europe/Moscow"))
    if date < local_now.date():
        raise HTTPException(status_code=400, detail="Cannot check slots for past dates")

    schedule = master.schedule_json or {}
    booking_days = min(int(schedule.get("booking_days", 90)), 90)
    if date > local_now.date() + timedelta(days=booking_days):
        return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": []})
    if is_schedule_date_excluded(schedule, date):
        return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": []})
    day_schedule = resolve_day_schedule(schedule, date)
    if not day_schedule or not day_schedule.get("active"):
        return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": []})

    work_start = day_schedule.get("work_start") or "00:00"
    work_end = day_schedule.get("work_end") or "23:59"
    break_start = day_schedule.get("break_start") or "13:00"
    break_end = day_schedule.get("break_end") or "14:00"
    try:
        work_start_t = time_type.fromisoformat(work_start) if isinstance(work_start, str) else work_start
        work_end_t = time_type.fromisoformat(work_end) if isinstance(work_end, str) else work_end
        break_start_t = time_type.fromisoformat(break_start) if isinstance(break_start, str) else break_start
        break_end_t = time_type.fromisoformat(break_end) if isinstance(break_end, str) else break_end
    except (TypeError, ValueError):
        logger.warning("Invalid schedule time for master %s on %s: %s", master_id, date, day_schedule)
        return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": []})
    if work_start_t >= work_end_t:
        return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": []})

    # Получаем bookings
    result = await db.execute(
        select(Booking).where(
            Booking.master_id == master_id,
            Booking.date == date,
            Booking.status.in_(["upcoming", "confirmed"]),
            Booking.id != exclude_booking_id if exclude_booking_id else True,
        )
    )
    bookings = result.scalars().all()

    # Получаем blocked_times
    blocked_result = await db.execute(
        select(BlockedTime).where(
            BlockedTime.master_id == master_id,
            BlockedTime.date == date,
        )
    )
    blocked_times = blocked_result.scalars().all()

    # Получаем активные SlotHold
    hold_result = await db.execute(
        select(SlotHold).where(
            SlotHold.master_id == master_id,
            SlotHold.date == date,
            SlotHold.expires_at > datetime.utcnow(),
        )
    )
    holds = hold_result.scalars().all()

    intervals = _calculate_slots(
        master,
        date,
        duration,
        bookings,
        blocked_times,
        holds,
        local_now,
    )
    return ApiResponse(success=True, data={"date": date, "duration": duration, "slots": intervals})


def _calculate_slots(master, target_date, duration, bookings, blocked_times, holds, local_now):
    schedule = master.schedule_json or {}
    if is_schedule_date_excluded(schedule, target_date):
        return []
    day_schedule = resolve_day_schedule(schedule, target_date)
    if not day_schedule or not day_schedule.get("active"):
        return []
    try:
        work_start_t = time_type.fromisoformat(day_schedule.get("work_start") or "00:00")
        work_end_t = time_type.fromisoformat(day_schedule.get("work_end") or "23:59")
        break_start_t = time_type.fromisoformat(day_schedule.get("break_start") or "13:00")
        break_end_t = time_type.fromisoformat(day_schedule.get("break_end") or "14:00")
    except (TypeError, ValueError):
        logger.warning("Invalid schedule time for master %s on %s: %s", master.id, target_date, day_schedule)
        return []
    if work_start_t >= work_end_t:
        return []

    intervals = []
    work_start_mins = time_to_minutes(work_start_t)
    work_end_mins = time_to_minutes(work_end_t)
    step = 15 if master.use_services else (master.interval_minutes or 60)
    if step <= 0 or step > 480:
        logger.warning("Invalid slot step for master %s: %s", master.id, step)
        step = 15 if master.use_services else 60
    guard = 0
    current_mins = work_start_mins
    while current_mins < work_end_mins:
        guard += 1
        if guard > 96:
            logger.warning("Slot generation guard stopped master %s date %s", master.id, target_date)
            break
        end_mins = current_mins + duration

        if end_mins > work_end_mins or end_mins > 24 * 60:
            break

        time_obj = time_type(current_mins // 60, current_mins % 60)
        end_current = time_type(end_mins // 60, end_mins % 60) if end_mins < 24 * 60 else END_OF_DAY
        current = _time_to_str(time_obj)

        available = True
        reason = None

        if target_date == local_now.date() and time_obj <= local_now.time():
            available = False
            reason = "past"

        # Проверяем пересечение с обедом: если service пересекается с обедом - недоступен
        if available and day_schedule.get("break_active", True) is not False and time_overlaps(time_obj, end_current, break_start_t, break_end_t):
            available = False
            reason = "break"

        if available:
            for b in bookings:
                b_time = b.time if isinstance(b.time, time_type) else time_type.fromisoformat(str(b.time))
                b_end = b.ends_at if hasattr(b, 'ends_at') and b.ends_at else _add_minutes(b_time, b.duration_minutes)
                if time_overlaps(time_obj, end_current, b_time, b_end):
                    available = False
                    reason = "booked"
                    break

        # Проверяем blocked_times
        if available and blocked_times:
            for blocked in blocked_times:
                bt_start = blocked.start_time if isinstance(blocked.start_time, time_type) else time_type.fromisoformat(str(blocked.start_time))
                bt_end = blocked.end_time if isinstance(blocked.end_time, time_type) else time_type.fromisoformat(str(blocked.end_time))
                if time_overlaps(time_obj, end_current, bt_start, bt_end):
                    available = False
                    reason = "blocked"
                    break

        # Проверяем SlotHold
        if available and holds:
            for hold in holds:
                h_time = hold.time if isinstance(hold.time, time_type) else time_type.fromisoformat(str(hold.time))
                h_end = interval_end(h_time, hold.duration_minutes or 60)
                if time_overlaps(time_obj, end_current, h_time, h_end):
                    available = False
                    reason = "held"
                    break

        intervals.append({"time": current, "available": available, "reason": reason})
        current_mins += step

    return intervals


@router.get("/{master_id:int}/availability", response_model=ApiResponse)
async def get_availability(
    master_id: int,
    date_from: date_type,
    date_to: date_type,
    duration: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    bot_id: int | None = None,
    vk_bot_id: int | None = None,
    vk_user: int | None = None,
    vk_sig: str | None = None,
    auth_ts: int | None = None,
    exclude_booking_id: Optional[int] = None,
):
    from backend.database import Master

    if duration < 15 or duration > 480:
        raise HTTPException(status_code=400, detail="Duration must be between 15 and 480 minutes")
    if date_to < date_from or (date_to - date_from).days > 41:
        raise HTTPException(status_code=400, detail="Date range must not exceed 42 days")
    if not await rate_limiter.check(f"public-availability:{client_ip_from_request(request)}"):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте через минуту")

    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    await _require_running_bot(db, master_id, bot_id, vk_bot_id, vk_user, vk_sig, auth_ts)
    try:
        local_now = datetime.now(ZoneInfo(master.timezone or "Europe/Moscow"))
    except Exception:
        local_now = datetime.now(ZoneInfo("Europe/Moscow"))

    booking_filter = [
        Booking.master_id == master_id,
        Booking.date >= date_from,
        Booking.date <= date_to,
        Booking.status.in_(["upcoming", "confirmed"]),
    ]
    if exclude_booking_id:
        booking_filter.append(Booking.id != exclude_booking_id)
    bookings = (await db.execute(select(Booking).where(*booking_filter))).scalars().all()
    blocked_times = (await db.execute(select(BlockedTime).where(
        BlockedTime.master_id == master_id,
        BlockedTime.date >= date_from,
        BlockedTime.date <= date_to,
    ))).scalars().all()
    holds = (await db.execute(select(SlotHold).where(
        SlotHold.master_id == master_id,
        SlotHold.date >= date_from,
        SlotHold.date <= date_to,
        SlotHold.expires_at > datetime.utcnow(),
    ))).scalars().all()

    bookings_by_date = {}
    blocked_by_date = {}
    holds_by_date = {}
    for item in bookings:
        bookings_by_date.setdefault(item.date, []).append(item)
    for item in blocked_times:
        blocked_by_date.setdefault(item.date, []).append(item)
    for item in holds:
        holds_by_date.setdefault(item.date, []).append(item)

    schedule = master.schedule_json or {}
    booking_days = min(int(schedule.get("booking_days", 90)), 90)
    last_open_date = local_now.date() + timedelta(days=booking_days)
    availability = {}
    cursor = date_from
    while cursor <= date_to:
        if cursor < local_now.date() or cursor > last_open_date:
            availability[cursor.isoformat()] = False
        else:
            slots = _calculate_slots(
                master,
                cursor,
                duration,
                bookings_by_date.get(cursor, []),
                blocked_by_date.get(cursor, []),
                holds_by_date.get(cursor, []),
                local_now,
            )
            availability[cursor.isoformat()] = any(slot["available"] for slot in slots)
        cursor += timedelta(days=1)

    return ApiResponse(success=True, data={"availability": availability})


@router.get("/{master_id:int}/menu", response_model=ApiResponse)
async def get_master_menu(
    master_id: int,
    bot_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from backend.database import MenuButton
    await _require_running_bot(db, master_id, bot_id)

    result = await db.execute(select(MenuButton).where(MenuButton.master_id == master_id))
    buttons = result.scalars().all()

    menu_data = {}
    for b in buttons:
        menu_data[b.button_type] = {"active": b.active, "content": b.content_json}

    return ApiResponse(success=True, data={"buttons": menu_data})


def _add_minutes(t: time_type, minutes: int) -> time_type:
    total = time_to_minutes(t) + minutes
    return time_type((total // 60) % 24, total % 60)


def _time_to_str(t: time_type) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"
