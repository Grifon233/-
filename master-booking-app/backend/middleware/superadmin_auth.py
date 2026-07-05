"""
Middleware для проверки прав супер-админа.
"""
from typing import Optional
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
# Единый источник ID супер-админа — чтобы значения не разъехались между модулями.
from backend.middleware.tg_auth import SUPERADMIN_ID


async def verify_superadmin(
    request: Request,
    db: Optional[AsyncSession] = None,
) -> dict:
    """
    Проверяет является ли пользователь супер-админом.
    Использует extract_tg_user для извлечения telegram_id из URL parameters.

    Returns:
        dict: Данные пользователя Telegram (id, username, first_name)

    Raises:
        HTTPException 401: Пользователь не авторизован (нет параметра user)
        HTTPException 403: Пользователь не является супер-админом
    """
    from backend.middleware.tg_auth import extract_tg_user

    tg_user = extract_tg_user(request)
    if not tg_user:
        raise HTTPException(
            status_code=401,
            detail="Не авторизован"
        )

    if tg_user["id"] != SUPERADMIN_ID:
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещён: требуются права супер-админа"
        )

    return tg_user