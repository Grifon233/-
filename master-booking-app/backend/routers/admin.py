import asyncio
from datetime import date as date_type
import logging
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import (
    Booking,
    BlockedTime,
    Client,
    ClientProfile,
    Master,
    MasterBot,
    MenuButton,
    Service,
    SlotHold,
    get_db,
)
from backend.client_profiles import telegram_profile_url
from backend.middleware.tg_auth import SUPERADMIN_ID, verify_auth_signature, verify_master_access, extract_tg_user
from backend.media_storage import get_upload_dir, normalize_media_reference, public_upload_url
from backend.schemas.schemas import (
    ApiResponse,
    MasterUpdate,
    ServiceCreate,
    ServiceUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)
DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_vk_media_tasks: dict[tuple[int, str], asyncio.Task] = {}


async def _prewarm_vk_menu_media(master_id: int, button_type: str, content: dict) -> None:
    from backend.database import async_session_maker, VkBot
    from backend.handlers.master_bot import extract_menu_button_photos, normalize_photo_url
    from backend.token_utils import decrypt_token
    from backend.vk.api import upload_photos_for_message

    photos = extract_menu_button_photos(button_type, content)
    photo_urls = [url for url in (normalize_photo_url(photo) for photo in photos) if url]
    if not photo_urls:
        return

    async with async_session_maker() as session:
        vk_bots = (await session.execute(
            select(VkBot).where(
                VkBot.master_id == master_id,
                VkBot.status == "running",
                VkBot.bot_type == "client",
                VkBot.owner_vk_id.isnot(None),
            )
        )).scalars().all()
    for vk_bot in vk_bots:
        attachments, failed = await upload_photos_for_message(
            decrypt_token(vk_bot.token),
            vk_bot.owner_vk_id,
            photo_urls,
        )
        logger.info(
            "VK media prewarm for master %s, bot %s: %d/%d ready",
            master_id,
            vk_bot.id,
            len(attachments),
            len(photo_urls),
        )
        if failed:
            logger.warning("VK media prewarm failed for %d photo(s), bot %s", len(failed), vk_bot.id)


def _schedule_vk_menu_media_prewarm(master_id: int, button_type: str, content: dict) -> None:
    if button_type not in {"address", "portfolio", "custom"}:
        return
    task_key = (master_id, button_type)
    current = _vk_media_tasks.get(task_key)
    if current and not current.done():
        return
    task = asyncio.create_task(_prewarm_vk_menu_media(master_id, button_type, content))
    _vk_media_tasks[task_key] = task

    def finish(completed: asyncio.Task) -> None:
        if _vk_media_tasks.get(task_key) is completed:
            _vk_media_tasks.pop(task_key, None)
        if not completed.cancelled() and completed.exception():
            logger.warning("VK media prewarm crashed: %s", completed.exception())

    task.add_done_callback(finish)


def _ensure_demo_is_readonly(master: Master, request: Request | None) -> None:
    """Reject every write to the public demo master."""
    if master.is_demo:
        raise HTTPException(status_code=403, detail="Демо-режим доступен только для просмотра")


def _looks_like_image(content: bytes) -> bool:
    """Проверка магических байт: JPEG, PNG, GIF, WEBP."""
    if len(content) < 12:
        return False
    if content[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if content[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if content[:6] in (b"GIF87a", b"GIF89a"):  # GIF
        return True
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":  # WEBP
        return True
    return False


@router.get("/auth-check", response_model=ApiResponse)
async def check_authorization(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Проверка авторизации - возвращает данные пользователя если авторизован"""
    tg_user = extract_tg_user(request)

    if not tg_user:
        return ApiResponse(success=False, data={"authorized": False})

    telegram_id = tg_user["id"]
    bot_id = request.query_params.get("bot_id")
    master = None
    if bot_id:
        try:
            bot = await db.get(MasterBot, int(bot_id))
        except (TypeError, ValueError):
            bot = None
        if bot and bot.master_telegram_id == telegram_id and getattr(bot, "master_id", None):
            master = await db.get(Master, bot.master_id)
    if not master and request.query_params.get("master_id"):
        try:
            candidate = await db.get(Master, int(request.query_params.get("master_id")))
        except (TypeError, ValueError):
            candidate = None
        if candidate and candidate.telegram_id == telegram_id:
            master = candidate
        elif candidate:
            result = await db.execute(
                select(MasterBot).where(
                    MasterBot.master_id == candidate.id,
                    MasterBot.master_telegram_id == telegram_id,
                    MasterBot.status == "running",
                )
            )
            if result.scalar_one_or_none():
                master = candidate
    if not master:
        result = await db.execute(
            select(Master).where(Master.telegram_id == telegram_id)
        )
        master = result.scalar_one_or_none()

    if not master:
        return ApiResponse(success=False, data={"authorized": False, "is_master": False})

    return ApiResponse(
        success=True,
        data={
            "authorized": True,
            "is_master": True,
            "master_id": master.id,
            "user": tg_user,
        }
    )


@router.get("/master", response_model=None)
async def get_master(
    db: AsyncSession = Depends(get_db),
    telegram_id: Optional[int] = None,
    master = Depends(verify_master_access),
) -> dict:
    """Получение данных мастера (требует авторизации)"""
    from backend import escape_text

    # Доступ разрешен только к мастеру из verify_master_access.
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")

    return ApiResponse(
        success=True,
        data={
            "id": master.id,
            "telegram_id": master.telegram_id,
            "name": escape_text(master.name),
            "avatar_url": normalize_media_reference(master.avatar_url),
            "telegram_username": master.telegram_username,
            "use_services": master.use_services,
            "interval_minutes": master.interval_minutes,
            "schedule": master.schedule_json,
            "subscription_required": master.subscription_required or False,
            "subscription_channel_id": master.subscription_channel_id,
            "subscription_text": master.subscription_text,
            "notify_new_bookings": master.notify_new_bookings,
            "notify_reminders": master.notify_reminders,
            "reminder_time": master.reminder_time or "18:00",
            "weekly_report_enabled": master.weekly_report_enabled,
            "timezone": master.timezone or "Europe/Moscow",
            "profile_link_warning_dismissed": master.profile_link_warning_dismissed or False,
            "is_demo": master.is_demo or False,
        },
    )


@router.put("/master", response_model=ApiResponse)
async def update_master(
    request: Request,
    data: MasterUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    _ensure_demo_is_readonly(master, request)

    from backend import escape_text

    # master уже получен из verify_master_access
    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"]:
        update_data["name"] = escape_text(update_data["name"])
    if "schedule_json" in update_data and update_data["schedule_json"]:
        update_data["schedule_json"] = normalize_schedule_payload(update_data["schedule_json"])

    for field, value in update_data.items():
        setattr(master, field, value)

    await db.commit()
    return ApiResponse(success=True, data={"id": master.id, "updated": True})


def _parse_hhmm(value: str) -> int | None:
    """'HH:MM' -> минуты от начала дня, или None если формат неверный."""
    try:
        hh, mm = str(value).split(":")
        minutes = int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None
    return minutes if 0 <= minutes <= 24 * 60 else None


def normalize_schedule_payload(schedule: dict) -> dict:
    normalized = dict(schedule)
    days = normalized.get("days")
    if not isinstance(days, list):
        return normalized

    fixed_days = []
    for index, item in enumerate(days):
        current = dict(item or {})
        if index < len(DAY_NAMES):
            current["day"] = current.get("day") or DAY_NAMES[index]
        day_label = current.get("day") or (DAY_NAMES[index] if index < len(DAY_NAMES) else "день")
        if current.get("active"):
            current["work_start"] = current.get("work_start") or "00:00"
            current["work_end"] = current.get("work_end") or "23:59"
            start = _parse_hhmm(current["work_start"])
            end = _parse_hhmm(current["work_end"])
            # Раньше можно было сохранить «работаю с 18:00 до 09:00»: расписание
            # молча ломалось и все даты гасли. Теперь отклоняем понятной ошибкой.
            if start is None or end is None or start >= end:
                raise HTTPException(
                    status_code=400,
                    detail=f"{day_label}: время начала работы должно быть раньше времени окончания.",
                )
            # Обед вне рабочих часов или «наизнанку» — просто выключаем, а не роняем день.
            break_start = _parse_hhmm(current.get("break_start") or "")
            break_end = _parse_hhmm(current.get("break_end") or "")
            if (
                break_start is None or break_end is None
                or break_start >= break_end
                or break_start < start or break_end > end
            ):
                current["break_active"] = False
        if not current.get("break_start") or not current.get("break_end"):
            current["break_active"] = False
        fixed_days.append(current)
    normalized["days"] = fixed_days
    return normalized


@router.get("/bookings", response_model=ApiResponse)
async def get_all_bookings(
    db: Annotated[AsyncSession, Depends(get_db)],
    date: Optional[date_type] = None,
    from_date: Optional[date_type] = None,
    to_date: Optional[date_type] = None,
    status: Optional[str] = None,
    master: Master = Depends(verify_master_access),
):
    # Изоляция по master_id
    query = select(Booking, Client).join(Client).where(Booking.master_id == master.id)
    if date:
        query = query.where(Booking.date == date)
    if from_date:
        query = query.where(Booking.date >= from_date)
    if to_date:
        query = query.where(Booking.date <= to_date)
    if status:
        query = query.where(Booking.status == status)

    result = await db.execute(query.order_by(Booking.date, Booking.time))
    rows = result.all()
    telegram_ids = {client.telegram_id for _, client in rows if client.telegram_id}
    profiles = {
        profile.telegram_id: profile
        for profile in (
            await db.execute(
                select(ClientProfile).where(ClientProfile.telegram_id.in_(telegram_ids))
            )
        ).scalars().all()
    } if telegram_ids else {}

    bookings_data = []
    for booking, client in rows:
        profile = profiles.get(client.telegram_id)
        profile_url = telegram_profile_url(
            client.telegram_id,
            profile.telegram_username if profile else None,
        )
        bookings_data.append(
            {
                "id": booking.id,
                "master_id": booking.master_id,
                "client": {
                    "id": client.id,
                    "name": client.name,
                    "phone": client.phone,
                    "telegram_id": client.telegram_id,
                    "telegram_username": profile.telegram_username if profile else None,
                    "telegram_profile_url": profile_url,
                },
                "date": booking.date,
                "time": booking.time,
                "duration_minutes": booking.duration_minutes,
                "service_id": booking.service_id,
                "service_ids": booking.service_ids or [],
                "service_name": booking.service_name,
                "status": booking.status,
                "comment": booking.comment,
                "master_comment": booking.master_comment,
            }
        )

    return ApiResponse(success=True, data={"bookings": bookings_data})


@router.put("/bookings/{booking_id}", response_model=ApiResponse)
async def update_booking(
    booking_id: int,
    data: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    from backend.database import BookingStatusHistory

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Тело запроса должно быть объектом")

    booking = await db.get(Booking, booking_id)
    if not booking or booking.master_id != master.id:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    if "date" in data or "time" in data:
        raise HTTPException(
            status_code=400,
            detail="Для переноса записи используйте специальное действие переноса",
        )
    if data.get("status") == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Для отмены записи используйте специальное действие отмены",
        )

    previous_status = booking.status
    allowed_fields = {"status", "comment", "master_comment"}
    unknown_fields = set(data) - allowed_fields
    if unknown_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемые поля: {', '.join(sorted(unknown_fields))}",
        )
    allowed_transitions = {
        "upcoming": {"confirmed", "completed", "no_show"},
        "confirmed": {"upcoming", "completed", "no_show"},
        "cancelled": set(),
        "completed": set(),
        "no_show": set(),
    }
    for field, value in data.items():
        if field == "status":
            if not isinstance(value, str):
                raise HTTPException(status_code=400, detail="Статус должен быть текстом")
            if value == previous_status:
                continue
            if value not in allowed_transitions.get(previous_status, set()):
                raise HTTPException(
                    status_code=409,
                    detail=f"Недопустимый переход статуса: {previous_status} -> {value}",
                )
        if field in {"comment", "master_comment"} and value is not None:
            if not isinstance(value, str):
                raise HTTPException(status_code=400, detail="Комментарий должен быть текстом")
            value = value.strip()
            if len(value) > 500:
                raise HTTPException(status_code=400, detail="Комментарий не должен превышать 500 символов")
        setattr(booking, field, value)

    # Фиксируем смену статуса в истории, чтобы аудит не терял событие
    # (раньше отмена через этот эндпоинт не оставляла следа).
    if booking.status != previous_status:
        db.add(BookingStatusHistory(
            booking_id=booking.id,
            old_status=previous_status,
            new_status=booking.status,
            changed_by="master",
        ))

    await db.commit()
    return ApiResponse(success=True, data={"id": booking.id, "updated": True})


@router.get("/services", response_model=ApiResponse)
async def get_services(
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    result = await db.execute(
        select(Service).where(Service.master_id == master.id, Service.active == True).order_by(Service.sort_order)
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
                    "sort_order": s.sort_order,
                }
                for s in services
            ],
        },
    )


@router.post("/services", response_model=ApiResponse)
async def create_service(
    request: Request,
    data: ServiceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    _ensure_demo_is_readonly(master, request)

    service = Service(master_id=master.id, **data.model_dump())
    db.add(service)
    await db.commit()
    await db.refresh(service)

    return ApiResponse(
        success=True,
        data={
            "id": service.id,
            "name": service.name,
            "price": service.price,
            "duration_minutes": service.duration_minutes,
            "active": service.active,
        },
    )


@router.put("/services/{service_id}", response_model=ApiResponse)
async def update_service(
    request: Request,
    service_id: int,
    data: ServiceUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    _ensure_demo_is_readonly(master, request)

    service = await db.get(Service, service_id)
    if not service or service.master_id != master.id:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(service, field, value)

    await db.commit()
    return ApiResponse(success=True, data={"id": service.id, "updated": True})


@router.delete("/services/{service_id}", response_model=ApiResponse)
async def delete_service(
    service_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
    request: Request = None,
):
    _ensure_demo_is_readonly(master, request)

    service = await db.get(Service, service_id)
    if not service or service.master_id != master.id:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    service.active = False
    await db.commit()

    return ApiResponse(success=True, data={"deleted": True, "soft_deleted": True})


@router.get("/menu-buttons", response_model=ApiResponse)
async def get_menu_buttons(
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    result = await db.execute(select(MenuButton).where(MenuButton.master_id == master.id))
    buttons = result.scalars().all()

    menu_data = {}
    for b in buttons:
        menu_data[b.button_type] = {"active": b.active, "content": b.content_json}

    return ApiResponse(success=True, data={"buttons": menu_data})


@router.put("/menu-buttons/{button_type}", response_model=ApiResponse)
async def update_menu_button(
    request: Request,
    button_type: str,
    data: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    master: Master = Depends(verify_master_access),
):
    _ensure_demo_is_readonly(master, request)

    result = await db.execute(
        select(MenuButton).where(MenuButton.master_id == master.id, MenuButton.button_type == button_type)
    )
    button = result.scalar_one_or_none()

    if button:
        button.active = data.get("active", button.active)
        button.content_json = data.get("content", button.content_json)
    else:
        button = MenuButton(
            master_id=master.id,
            button_type=button_type,
            active=data.get("active", False),
            content_json=data.get("content", {}),
        )
        db.add(button)
        await db.flush()
        # Set active separately after flush since column has default
        if "active" in data:
            button.active = data["active"]

    await db.commit()
    _schedule_vk_menu_media_prewarm(master.id, button_type, button.content_json or {})
    return ApiResponse(success=True, data={"updated": True})


@router.post("/upload", response_model=ApiResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    file_type: str = Form(...),
    master: Master = Depends(verify_master_access),
):
    _ensure_demo_is_readonly(master, request)


    allowed_types = {"avatar", "portfolio", "menu"}
    if file_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Unsupported file_type")

    content_type = (file.content_type or "").lower()
    allowed_content_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    content = await file.read()
    max_size = 5 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="File is too large")

    # Заголовок Content-Type подделывается — проверяем реальную сигнатуру файла.
    if not _looks_like_image(content):
        raise HTTPException(status_code=400, detail="Файл не является изображением")

    suffix_by_type = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    filename = f"{file_type}_{master.id}_{uuid4().hex}{suffix_by_type[content_type]}"
    upload_dir = get_upload_dir()
    filepath = upload_dir / filename

    temporary_path = filepath.with_suffix(f"{filepath.suffix}.tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(filepath)

    return ApiResponse(
        success=True,
        data={"url": public_upload_url(filename)},
    )
