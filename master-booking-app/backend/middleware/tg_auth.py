"""
Middleware для авторизации через Telegram.
Проверяет telegram_id в URL и сверяет с базой данных.
Основано на паттерне из: https://github.com/iCodeCraft/telegram-init-data
"""
from typing import Optional, Annotated
import hashlib
import hmac
import logging
import os
import json
import time
from urllib.parse import parse_qsl, unquote

from fastapi import HTTPException, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, Master, MasterBot, VkBot

logger = logging.getLogger(__name__)


def _auth_secret() -> str | None:
    return os.getenv("AUTH_SIGNING_SECRET") or os.getenv("ARCHITECT_TOKEN")


# Ссылки из бота действительны 10 дней. После — нужно заново открыть бота
# и нажать «Старт», чтобы получить свежую ссылку.
LINK_TTL_SECONDS = 10 * 24 * 60 * 60
# Имя сохранено для обратной совместимости со старым кодом/тестами.
MASTER_LINK_TTL_SECONDS = LINK_TTL_SECONDS
# Небольшой допуск на расхождение часов клиента/сервера.
_CLOCK_SKEW_SECONDS = 300

# Сообщения подобраны так, чтобы фронтенд показывал понятное окно с просьбой
# заново открыть бота. Оба содержат слово «Старт» — по нему фронтенд их ловит.
LINK_INVALID_DETAIL = (
    "Ссылка недействительна. Откройте бота мастера и нажмите «Старт», "
    "чтобы получить новую ссылку."
)
LINK_EXPIRED_DETAIL = (
    "Ссылка устарела. Откройте бота и нажмите «Старт», "
    "чтобы получить новую ссылку для входа."
)
AUTH_NOT_CONFIGURED_DETAIL = (
    "Сервер авторизации временно недоступен. Попробуйте немного позже."
)


def sign_auth_params(user_id: int, auth_ts: int | None = None) -> str | None:
    secret = _auth_secret()
    if not secret:
        return None
    payload = f"user={int(user_id)}"
    if auth_ts is not None:
        payload += f"&auth_ts={int(auth_ts)}"
    payload = payload.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_auth_signature(request: Request, user_id: int, require_fresh: bool = True) -> None:
    """Проверяет подпись ссылки.

    Fail-closed: если секрет подписи не настроен на сервере — отклоняем запрос
    (а не пропускаем, как было раньше). Подпись обязательна всегда; при
    require_fresh ссылка также не должна быть старше LINK_TTL_SECONDS (10 дней).
    """
    secret = _auth_secret()
    if not secret:
        logger.critical(
            "AUTH_SIGNING_SECRET/ARCHITECT_TOKEN не настроен — отклоняю подписанный запрос. "
            "Авторизация по ссылкам работать не будет, пока секрет не задан."
        )
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED_DETAIL)

    provided = request.query_params.get("sig")
    if not provided:
        raise HTTPException(status_code=401, detail=LINK_INVALID_DETAIL)

    auth_ts_raw = request.query_params.get("auth_ts")
    auth_ts = None
    if auth_ts_raw:
        try:
            auth_ts = int(auth_ts_raw)
        except ValueError:
            raise HTTPException(status_code=401, detail=LINK_INVALID_DETAIL)

    expected = sign_auth_params(user_id, auth_ts)
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail=LINK_INVALID_DETAIL)

    if require_fresh:
        now = int(time.time())
        if auth_ts is None or now - auth_ts > LINK_TTL_SECONDS:
            raise HTTPException(status_code=401, detail=LINK_EXPIRED_DETAIL)
        if auth_ts - now > _CLOCK_SKEW_SECONDS:
            # Ссылка «из будущего» — подделка времени.
            raise HTTPException(status_code=401, detail=LINK_INVALID_DETAIL)


async def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
    """
    Проверяет Telegram WebApp initData и возвращает данные пользователя.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app

    Args:
        init_data: Строка initData из Telegram WebApp
        bot_token: Токен конкретного бота для проверки

    Returns:
        dict: Данные пользователя {id, username, first_name, last_name}

    Raises:
        HTTPException: Если проверка не пройдена
    """
    if not bot_token:
        raise HTTPException(status_code=400, detail="Telegram bot token not configured")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    try:
        # Парсим initData с учётом URL encoding
        init_data_dict = dict(parse_qsl(init_data))
        hash_value = init_data_dict.pop('hash', '')
        auth_date_str = init_data_dict.get('auth_date', '0')

        # Проверяем свежесть auth_date (не старше 24 часов)
        auth_date = int(auth_date_str)
        current_time = int(time.time())
        if current_time - auth_date > 24 * 60 * 60:  # 24 часа
            raise HTTPException(status_code=401, detail="Telegram initData expired")

        # Сортируем параметры и формируем data_check_string
        sorted_params = sorted(f"{k}={unquote(v)}" for k, v in init_data_dict.items())
        data_check_string = "\n".join(sorted_params)

        # Проверяем подпись
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, hash_value):
            raise HTTPException(status_code=401, detail="Invalid Telegram initData signature")

        # Извлекаем данные пользователя
        user_data = init_data_dict.get('user', '{}')
        user = json.loads(user_data)

        return {
            "id": user.get("id"),
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Telegram initData: {str(e)}")


async def _get_master_bot_token(db: AsyncSession, master_id: int) -> str:
    """Получает токен бота для конкретного мастера (с расшифровкой)."""
    # Сначала ищем мастера
    master = await db.get(Master, master_id)
    if not master:
        return os.getenv("TELEGRAM_BOT_TOKEN")

    # Ищем бота мастера
    from backend.token_utils import decrypt_token

    if getattr(master, "telegram_id", None):
        result = await db.execute(
            select(MasterBot.token).where(
                (MasterBot.master_id == master.id) | (MasterBot.master_telegram_id == master.telegram_id)
            )
        )
    else:
        result = await db.execute(select(MasterBot.token).where(MasterBot.master_id == master.id))
    bot_token = result.scalars().first()

    if bot_token:
        return decrypt_token(bot_token)

    # Fallback к основному боту, если не найден
    return os.getenv("TELEGRAM_BOT_TOKEN")


class VerifyMasterAccess:
    """Class-based dependency для проверки авторизации мастера"""

    async def __call__(
        self,
        request: Request,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Master:
        """Проверяет авторизацию по параметрам URL:
        - ?bot_id=X&user=Y&username=Z&name=W

        Возвращает Master если авторизация успешна.
        """
        user_id = request.query_params.get("user")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Не авторизован: отсутствует параметр user"
            )

        try:
            telegram_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректный параметр user")

        verify_auth_signature(request, telegram_id, require_fresh=True)

        bot_id = request.query_params.get("bot_id")
        if bot_id:
            try:
                bot_id_int = int(bot_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Некорректный параметр bot_id")
            bot = await db.get(MasterBot, bot_id_int)
            if not bot or bot.master_telegram_id != telegram_id or bot.status != "running":
                raise HTTPException(status_code=403, detail="Доступ к боту приостановлен")
            master = await db.get(Master, bot.master_id) if getattr(bot, "master_id", None) else None
        else:
            master_id = request.query_params.get("master_id")
            if not master_id:
                raise HTTPException(status_code=403, detail="Отсутствует параметр bot_id")
            try:
                master_id_int = int(master_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Некорректный параметр master_id")
            master = await db.get(Master, master_id_int)
            if master and master.telegram_id != telegram_id:
                result = await db.execute(
                    select(MasterBot).where(
                        MasterBot.master_id == master.id,
                        MasterBot.master_telegram_id == telegram_id,
                        MasterBot.status == "running",
                    )
                )
                owns_telegram_bot = result.scalar_one_or_none() is not None
                if not owns_telegram_bot:
                    vk_result = await db.execute(
                        select(VkBot).where(
                            VkBot.master_id == master.id,
                            VkBot.master_telegram_id == telegram_id,
                            VkBot.status == "running",
                        )
                    )
                    if not vk_result.scalar_one_or_none():
                        raise HTTPException(status_code=403, detail="Вы не являетесь владельцем этого бота")

        if not master:
            result = await db.execute(
                select(Master).where(Master.telegram_id == telegram_id)
            )
            master = result.scalar_one_or_none()
        if not master:
            raise HTTPException(
                status_code=403,
                detail="Доступ запрещён: профиль бота не найден"
            )
        if master.is_demo:
            raise HTTPException(status_code=403, detail="Демо-режим доступен только для просмотра")
        return master


verify_master_access = VerifyMasterAccess()


async def verify_bot_owner(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[Master, Optional[MasterBot]]:
    """Проверяет что запрос от владельца бота"""
    user_id = request.query_params.get("user")
    bot_id = request.query_params.get("bot_id")

    if not user_id or not bot_id:
        raise HTTPException(
            status_code=401,
            detail="Отсутствуют параметры авторизации"
        )

    try:
        telegram_id = int(user_id)
        bot_id_int = int(bot_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректные параметры авторизации")
    verify_auth_signature(request, telegram_id)

    result = await db.execute(
        select(MasterBot).where(MasterBot.id == bot_id_int)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Бот не найден")

    if bot.master_telegram_id != telegram_id:
        raise HTTPException(
            status_code=403,
            detail="Вы не являетесь владельцем этого бота"
        )
    if bot.status != "running":
        raise HTTPException(status_code=403, detail="Доступ к боту приостановлен")

    master = await db.get(Master, bot.master_id) if getattr(bot, "master_id", None) else None
    if not master:
        result = await db.execute(
            select(Master).where(Master.telegram_id == telegram_id)
        )
        master = result.scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=403, detail="Профиль бота не найден")

    return master, bot


SUPERADMIN_ID = 623597334


def extract_tg_user(request: Request) -> Optional[dict]:
    """Извлекает данные пользователя Telegram из URL parameters"""
    user_id = request.query_params.get("user")
    if not user_id:
        user_id = request.query_params.get("user_id")
    if not user_id:
        return None

    try:
        tg_id = int(user_id)
        verify_auth_signature(request, tg_id)
    except (ValueError, HTTPException):
        return None

    return {
        "id": tg_id,
        "username": request.query_params.get("username"),
        "first_name": request.query_params.get("name"),
        "last_name": None,
    }


def build_admin_url(
    base_url: str,
    user_id: int,
    username: str = None,
    name: str = None,
) -> str:
    """Строит URL для админки с безопасным кодированием query-параметров."""
    from urllib.parse import urlencode

    auth_ts = int(time.time())
    params = {"user": user_id, "auth_ts": auth_ts}
    sig = sign_auth_params(user_id, auth_ts)
    if sig:
        params["sig"] = sig
    if username:
        params["username"] = username
    if name:
        params["name"] = name

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"
