"""
API управления короткими ссылками.
Автосокращение URL без внешних сервисов.
"""
import string
import random
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import ShortUrl, get_db
from backend.middleware.tg_auth import verify_master_access
from backend.schemas.schemas import ApiResponse
from backend.config import build_url
from backend.rate_limiter import client_ip_from_request, rate_limiter

router = APIRouter(prefix="/shorten", tags=["shorten"])

CODE_LENGTH = 6


def build_short_url(code: str) -> str:
    return build_url(f"/s/{code}")
SAFE_PUBLIC_PREFIXES = (
    "https://t.me/",
    "https://telegram.me/",
    "https://wa.me/",
    "tel:",
    "mailto:",
)


def generate_code(length: int = CODE_LENGTH) -> str:
    """Генерирует случайный код из букв и цифр."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


@router.post("", response_model=ApiResponse)
async def shorten_url(
    url: Annotated[str, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
):
    """
    Создаёт короткую ссылку для длинного URL.
    Если URL уже сокращался, возвращает существующий код.
    """
    if not url or len(url) < 10:
        raise HTTPException(status_code=400, detail="URL слишком короткий")

    if not url.startswith(("http://", "https://", "tel:", "mailto:")):
        raise HTTPException(status_code=400, detail="Некорректный URL")

    if not any(url.startswith(prefix) for prefix in SAFE_PUBLIC_PREFIXES):
        # Generic short links are persisted globally, so require master auth.
        await verify_master_access(request, db)

    if not await rate_limiter.check(f"shorten:{client_ip_from_request(request)}"):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")

    # Проверяем, есть ли уже такой URL
    result = await db.execute(select(ShortUrl).where(ShortUrl.original_url == url))
    existing = result.scalar_one_or_none()

    if existing:
        return ApiResponse(success=True, data={
            "code": existing.code,
            "short_url": build_short_url(existing.code),
            "original_url": existing.original_url,
        })

    # Генерируем уникальный код
    for _ in range(10):  # до 10 попыток
        code = generate_code()
        result = await db.execute(select(ShortUrl).where(ShortUrl.code == code))
        if not result.scalar_one_or_none():
            break
    else:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать код")

    short = ShortUrl(code=code, original_url=url)
    db.add(short)
    await db.commit()
    await db.refresh(short)

    return ApiResponse(success=True, data={
        "code": short.code,
        "short_url": build_short_url(short.code),
        "original_url": short.original_url,
    })
