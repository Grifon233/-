"""
API управления слотами.
Создание/проверка/удаление временных блокировок (soft holds).
"""
from datetime import datetime, timedelta, date, time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import Master, MasterBot, SlotHold, get_db
from backend.schemas.schemas import ApiResponse
from backend.time_utils import intervals_overlap

router = APIRouter(prefix="/slots", tags=["slots"])

# Время жизни hold в минутах
HOLD_TTL_MINUTES = 5
# Предел активных блокировок на одного мастера — защита от флуда (DoS на запись).
# Понижен: система холдов сейчас не используется фронтендом, поэтому большой
# запас не нужен, а меньший потолок ограничивает возможное злоупотребление API.
MAX_ACTIVE_HOLDS_PER_MASTER = 40


async def _require_running_bot_for_hold(db: AsyncSession, master_id: int, bot_id: int | None) -> None:
    """Холд можно ставить только по живой ссылке записи (работающий бот мастера).

    Без этого любой мог бесконтрольно блокировать все слоты мастера.
    """
    master = await db.get(Master, master_id)
    if not master:
        raise HTTPException(status_code=404, detail="Мастер не найден")
    if master.is_demo:
        return
    if not bot_id:
        raise HTTPException(status_code=403, detail="Ссылка записи недоступна. Откройте бота и нажмите /start.")
    bot = await db.get(MasterBot, bot_id)
    linked = bool(bot) and (
        (bot.master_id == master.id) if getattr(bot, "master_id", None) else (bot.master_telegram_id == master.telegram_id)
    )
    if not bot or not linked or bot.status != "running":
        raise HTTPException(status_code=403, detail="Ссылка записи недоступна. Откройте бота и нажмите /start.")


@router.post("/hold", response_model=ApiResponse)
async def create_slot_hold(
    db: Annotated[AsyncSession, Depends(get_db)],
    master_id: int,
    slot_date: date,
    slot_time: time,
    session_id: str,
    duration_minutes: int = 60,
    bot_id: Optional[int] = None,
):
    """
    Создать временную блокировку слота.
    Проверяет пересечение интервалов, а не точное время.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    if duration_minutes < 15 or duration_minutes > 480:
        raise HTTPException(status_code=400, detail="duration_minutes must be between 15 and 480")

    await _require_running_bot_for_hold(db, master_id, bot_id)

    await db.execute(delete(SlotHold).where(SlotHold.expires_at <= datetime.utcnow()))

    active_total = await db.scalar(
        select(func.count(SlotHold.id)).where(
            SlotHold.master_id == master_id,
            SlotHold.expires_at > datetime.utcnow(),
        )
    )
    if active_total and active_total >= MAX_ACTIVE_HOLDS_PER_MASTER:
        raise HTTPException(status_code=429, detail="Слишком много активных блокировок. Попробуйте позже.")

    # Все активные holds этого мастера на дату
    existing = await db.execute(
        select(SlotHold).where(
            SlotHold.master_id == master_id,
            SlotHold.date == slot_date,
            SlotHold.expires_at > datetime.utcnow(),
        )
    )
    active_holds = existing.scalars().all()
    own_holds = [hold for hold in active_holds if hold.session_id == session_id]
    # Проверяем пересечение по интервалам
    own_overlap = None
    for h in active_holds:
        if intervals_overlap(slot_time, duration_minutes, h.time, h.duration_minutes or 60):
            if h.session_id == session_id:
                own_overlap = h
            else:
                raise HTTPException(
                    status_code=409,
                    detail="Слот временно заблокирован другим клиентом"
                )

    if own_overlap:
        # Обновляем TTL и duration для своего hold
        own_overlap.expires_at = datetime.utcnow() + timedelta(minutes=HOLD_TTL_MINUTES)
        own_overlap.duration_minutes = duration_minutes
        await db.commit()
        return ApiResponse(success=True, data={
            "hold_id": own_overlap.id,
            "expires_at": own_overlap.expires_at.isoformat(),
        })

    if len(own_holds) >= 2:
        raise HTTPException(status_code=429, detail="Слишком много активных блокировок слотов")

    # Создаём новый hold
    expires_at = datetime.utcnow() + timedelta(minutes=HOLD_TTL_MINUTES)
    hold = SlotHold(
        master_id=master_id,
        date=slot_date,
        time=slot_time,
        duration_minutes=duration_minutes,
        session_id=session_id,
        expires_at=expires_at,
    )
    db.add(hold)
    await db.commit()
    await db.refresh(hold)

    return ApiResponse(success=True, data={
        "hold_id": hold.id,
        "expires_at": hold.expires_at.isoformat(),
        "ttl_minutes": HOLD_TTL_MINUTES
    })


@router.delete("/hold/{hold_id}", response_model=ApiResponse)
async def release_slot_hold(
    hold_id: int,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Удалить (освободить) временную блокировку"""
    hold = await db.get(SlotHold, hold_id)
    if not hold:
        return ApiResponse(success=True, data={"released": False, "reason": "not_found"})

    if hold.session_id != session_id:
        raise HTTPException(status_code=403, detail="Нельзя удалить чужой hold")

    await db.delete(hold)
    await db.commit()
    return ApiResponse(success=True, data={"released": True})


@router.post("/holds/cleanup", response_model=ApiResponse)
async def cleanup_expired_holds(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Удалить просроченные holds (запускать по cron)"""
    result = await db.execute(
        select(SlotHold).where(SlotHold.expires_at < datetime.utcnow())
    )
    expired = result.scalars().all()
    for h in expired:
        await db.delete(h)
    await db.commit()
    return ApiResponse(success=True, data={"cleaned": len(expired)})
