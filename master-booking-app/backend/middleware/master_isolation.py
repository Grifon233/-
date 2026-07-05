"""
Middleware для автоматической изоляции данных по master_id.
Все endpoints получают master_id из авторизации и фильтруют данные.
"""
from typing import Optional
from fastapi import Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, Master


class MasterContext:
    """Контекст текущего мастера для запроса"""

    def __init__(self, master_id: int, telegram_id: int):
        self.master_id = master_id
        self.telegram_id = telegram_id

    def __repr__(self):
        return f"MasterContext(master_id={self.master_id}, telegram_id={self.telegram_id})"


async def get_current_master(
    request: Request,
    db: AsyncSession,
) -> MasterContext:
    """
    Dependency для получения контекста текущего мастера.
    Извлекает telegram_id из URL parameters и находит master_id.

    Использование:
        @router.get("/bookings")
        async def get_bookings(ctx: MasterContext = Depends(get_current_master)):
            # ctx.master_id содержит ID текущего мастера
    """
    user_id = request.query_params.get("user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Не авторизован")

    try:
        telegram_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректный параметр user")

    # Обязательная проверка подписи: без неё этот helper был бы дырой
    # (доступ по одному только telegram_id из URL).
    from backend.middleware.tg_auth import verify_auth_signature
    verify_auth_signature(request, telegram_id)

    from sqlalchemy import select
    result = await db.execute(
        select(Master).where(Master.telegram_id == telegram_id)
    )
    master = result.scalar_one_or_none()

    if not master:
        raise HTTPException(status_code=403, detail="Мастер не найден")

    return MasterContext(master_id=master.id, telegram_id=telegram_id)


async def get_master_id(
    request: Request,
    db: AsyncSession,
) -> int:
    """
    Простой dependency возвращающий только master_id.
    Использовать когда не нужны другие данные мастера.
    """
    ctx = await get_current_master(request, db)
    return ctx.master_id


def filter_by_master(query, model, master_id: int):
    """
    Утилита для добавления фильтра по master_id к SQLAlchemy запросу.

    Usage:
        query = filter_by_master(query, Booking, master_id)
    """
    return query.where(model.master_id == master_id)


class MasterIsolation:
    """
    Mixin для автоматической изоляции запросов по master_id.

    Usage:
        class BookingRepository(MasterIsolation):
            async def get_all(self, master_id: int):
                return await self._get_filtered(Booking, master_id)
    """

    async def _get_filtered(self, model, master_id: int, **filters):
        """Получить записи с фильтрацией по master_id"""
        from sqlalchemy import select
        from backend.database import async_session_maker

        async with async_session_maker() as db:
            query = select(model).where(model.master_id == master_id)
            for key, value in filters.items():
                if hasattr(model, key):
                    query = query.where(getattr(model, key) == value)

            result = await db.execute(query)
            return result.scalars().all()

    async def _get_one(self, model, master_id: int, item_id: int):
        """Получить одну запись с проверкой ownership"""
        from backend.database import async_session_maker

        async with async_session_maker() as db:
            item = await db.get(model, item_id)
            if not item or item.master_id != master_id:
                return None
            return item