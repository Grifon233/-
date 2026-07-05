from datetime import date, datetime, time as time_type, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.time_utils import is_schedule_date_excluded

from backend.database import BlockedTime, Booking, Client, Master, Service, get_db, get_demo_master
from backend.handlers.master_bot import get_custom_button_items, is_meaningful_custom_button
from backend.media_storage import normalize_media_reference
from backend.schemas.schemas import ApiResponse

router = APIRouter(prefix="/demo", tags=["demo"])


# Демо-режим всегда включен для demo endpoints (master_id=1)
def is_demo_master() -> bool:
    """Всегда возвращает True - demo endpoints только для демо-мастера"""
    return True


@router.post("/register", response_model=ApiResponse)
async def demo_register(
    telegram_id: int,
    name: str,
    phone: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    demo_mode = is_demo_master()

    result = await db.execute(select(Client).where(Client.telegram_id == telegram_id))
    client = result.scalar_one_or_none()

    if demo_mode:
        return ApiResponse(
            success=True,
            data={"client_id": 999998, "name": name, "phone": phone, "demo_mode": True}
        )

    demo_master = await get_demo_master(db)

    if client:
        client.name = name
        client.phone = phone
    else:
        client = Client(master_id=demo_master.id, telegram_id=telegram_id, name=name, phone=phone)
        db.add(client)

    await db.commit()
    await db.refresh(client)

    return ApiResponse(success=True, data={"client_id": client.id, "name": client.name, "phone": client.phone})


@router.get("/master", response_model=ApiResponse)
async def demo_master(db: Annotated[AsyncSession, Depends(get_db)]):
    """Возвращает данные демо-мастера (без авторизации)"""
    demo_master = await get_demo_master(db)

    return ApiResponse(success=True, data={
        "id": demo_master.id,
        "telegram_id": demo_master.telegram_id,
        "name": demo_master.name,
        "avatar_url": normalize_media_reference(demo_master.avatar_url),
        "telegram_username": demo_master.telegram_username,
        "use_services": demo_master.use_services,
        "interval_minutes": demo_master.interval_minutes,
        "schedule": demo_master.schedule_json,
        "subscription_required": demo_master.subscription_required or False,
        "subscription_channel_id": demo_master.subscription_channel_id,
        "subscription_text": demo_master.subscription_text,
        "is_demo": True,
    })


@router.get("/services", response_model=ApiResponse)
async def demo_services(db: Annotated[AsyncSession, Depends(get_db)]):
    demo_master = await get_demo_master(db)
    result = await db.execute(select(Service).where(Service.master_id == demo_master.id).order_by(Service.sort_order))
    services = result.scalars().all()

    return ApiResponse(success=True, data={"services": [{"id": s.id, "name": s.name, "price": s.price, "duration_minutes": s.duration_minutes, "active": s.active} for s in services]})


@router.get("/schedule", response_model=ApiResponse)
async def demo_schedule(db: Annotated[AsyncSession, Depends(get_db)]):
    demo_master = await get_demo_master(db)

    return ApiResponse(success=True, data={"schedule": demo_master.schedule_json, "interval_minutes": demo_master.interval_minutes})


@router.get("/slots", response_model=ApiResponse)
async def demo_slots(
    db: Annotated[AsyncSession, Depends(get_db)],
    date_str: str = "2026-05-20",
    duration: int = 60,
):
    booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    demo_master = await get_demo_master(db)

    schedule = demo_master.schedule_json or {}
    if is_schedule_date_excluded(schedule, booking_date):
        return ApiResponse(success=True, data={"date": date_str, "slots": []})
    if demo_master.use_services and duration == 15:
        min_duration = await db.scalar(
            select(func.min(Service.duration_minutes)).where(Service.master_id == demo_master.id, Service.active == True)
        )
        duration = min_duration or duration
    days = schedule.get("days", [])
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_index = booking_date.weekday()
    day_name = day_names[day_index]

    day_schedule = next((d for d in days if d.get("day") == day_name), None)
    if not day_schedule or not day_schedule.get("active"):
        return ApiResponse(success=True, data={"date": date_str, "slots": []})

    work_start = day_schedule.get("work_start", "09:00")
    work_end = day_schedule.get("work_end", "18:00")
    break_start = day_schedule.get("break_start", "13:00")
    break_end = day_schedule.get("break_end", "14:00")

    result = await db.execute(select(Booking).where(Booking.master_id == demo_master.id, Booking.date == booking_date, Booking.status == "upcoming"))
    bookings = result.scalars().all()

    slots = []
    start_h, start_m = map(int, work_start.split(":"))
    end_h, end_m = map(int, work_end.split(":"))
    STEP = 15  # 15-minute intervals between slots

    current_h, current_m = start_h, start_m
    while True:
        current_time = f"{current_h:02d}:{current_m:02d}"
        # Calculate end time if booking this slot with given duration
        start_total = current_h * 60 + current_m
        end_total = start_total + duration
        end_h_calc = end_total // 60
        end_m_calc = end_total % 60

        # Check if booking would extend beyond work end
        if end_h_calc > end_h or (end_h_calc == end_h and end_m_calc > end_m):
            break

        available = True
        reason = None

        # Check break time
        break_start_t = time_type(*map(int, break_start.split(":")))
        break_end_t = time_type(*map(int, break_end.split(":")))
        current_t = time_type(current_h, current_m)
        end_t = time_type(end_h_calc, end_m_calc)
        if current_t < break_end_t and end_t > break_start_t:
            available = False
            reason = "break"

        # Check existing bookings
        if available:
            for b in bookings:
                b_time = b.time if isinstance(b.time, time_type) else datetime.strptime(str(b.time), "%H:%M:%S").time()
                b_end_mins = b_time.hour * 60 + b_time.minute + b.duration_minutes
                b_end = time_type(b_end_mins // 60, b_end_mins % 60)
                if current_t < b_end and end_t > b_time:
                    available = False
                    reason = "booked"
                    break

        slots.append({"time": current_time, "available": available, "reason": reason})

        # Step by 15 minutes
        current_m += STEP
        while current_m >= 60:
            current_h += 1
            current_m -= 60

        if current_h > end_h or (current_h == end_h and current_m > end_m):
            break

    return ApiResponse(success=True, data={"date": date_str, "slots": slots})


@router.post("/book", response_model=ApiResponse)
async def demo_book(
    db: Annotated[AsyncSession, Depends(get_db)],
    telegram_id: int = 0,
    name: str = "",
    phone: str = "",
    service_id: int = 1,
    date_str: str = "2026-05-20",
    time_str: str = "10:00",
):
    demo_mode = is_demo_master()

    # Demo режим - симулируем успех без сохранения
    if demo_mode:
        return ApiResponse(
            success=True,
            data={
                "booking_id": 999997,
                "client_name": name,
                "service": f"Услуга {service_id}",
                "date": date_str,
                "time": time_str,
                "demo_mode": True,
            }
        )

    demo_master = await get_demo_master(db)

    result = await db.execute(select(Client).where(Client.telegram_id == telegram_id))
    client = result.scalar_one_or_none()

    if not client:
        client = Client(master_id=demo_master.id, telegram_id=telegram_id, name=name, phone=phone)
        db.add(client)
        await db.flush()

    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="SERVICE_NOT_FOUND")

    booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    booking_time = datetime.strptime(time_str, "%H:%M").time()

    booking = Booking(master_id=demo_master.id, client_id=client.id, date=booking_date, time=booking_time, duration_minutes=service.duration_minutes, service_ids=[service_id], status="upcoming")
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return ApiResponse(success=True, data={"booking_id": booking.id, "client_name": name, "service": service.name, "date": date_str, "time": time_str, "price": service.price})


@router.get("/bookings/master", response_model=ApiResponse)
async def demo_master_bookings(db: Annotated[AsyncSession, Depends(get_db)]):
    demo_master = await get_demo_master(db)
    result = await db.execute(select(Booking, Client).join(Client).where(Booking.master_id == demo_master.id, Booking.status == "upcoming").order_by(Booking.date, Booking.time))
    rows = result.all()
    service_ids = {
        service_id
        for booking, _client in rows
        for service_id in (booking.service_ids or [])
    }
    services_by_id = {
        service.id: service
        for service in (
            await db.execute(
                select(Service).where(
                    Service.master_id == demo_master.id,
                    Service.id.in_(service_ids),
                )
            )
        ).scalars().all()
    } if service_ids else {}

    bookings = []
    for booking, client in rows:
        service_names = [
            services_by_id[service_id].name
            for service_id in (booking.service_ids or [])
            if service_id in services_by_id
        ]

        bookings.append({
            "id": booking.id,
            "master_id": booking.master_id,
            "client": {
                "id": client.id,
                "name": client.name,
                "phone": client.phone,
                "telegram_id": client.telegram_id,
            },
            "client_name": client.name,
            "client_phone": client.phone,
            "services": service_names,
            "service_name": booking.service_name or ", ".join(service_names),
            "date": booking.date.isoformat(),
            "time": str(booking.time),
            "duration_minutes": booking.duration_minutes,
            "status": booking.status,
            "comment": booking.comment,
            "master_comment": booking.master_comment,
        })

    return ApiResponse(success=True, data={"bookings": bookings})


@router.delete("/bookings/{booking_id}", response_model=ApiResponse)
async def demo_cancel_booking(booking_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    demo_mode = is_demo_master()

    if demo_mode:
        return ApiResponse(success=True, data={"id": booking_id, "status": "cancelled", "demo_mode": True})

    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    # Проверяем, что запись принадлежит демо-мастеру
    demo_master = await get_demo_master(db)
    if booking.master_id != demo_master.id:
        raise HTTPException(status_code=403, detail="Отмена разрешена только для записей демо-мастера")

    booking.status = "cancelled"
    await db.commit()

    return ApiResponse(success=True, data={"id": booking_id, "status": "cancelled"})


@router.get("/menu-buttons", response_model=ApiResponse)
async def demo_menu_buttons(db: Annotated[AsyncSession, Depends(get_db)]):
    """Возвращает настройки кнопок меню демо-мастера (без авторизации)"""
    from backend.database import MenuButton

    demo_master = await get_demo_master(db)
    result = await db.execute(select(MenuButton).where(MenuButton.master_id == demo_master.id))
    buttons = result.scalars().all()

    menu_data = {}
    for b in buttons:
        active = b.active
        if b.button_type == "custom":
            active = any(
                item.get("active") and is_meaningful_custom_button(item)
                for item in get_custom_button_items(b.content_json or {})
            )
        menu_data[b.button_type] = {"active": active, "content": b.content_json}

    return ApiResponse(success=True, data={"buttons": menu_data})
