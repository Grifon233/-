"""Verified Telegram client registration shared by all master bots."""
import hashlib
import hmac
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import Client, ClientProfile


_NAME_PART = re.compile(r"^[A-Za-zА-Яа-яЁё]+(?:[-'][A-Za-zА-Яа-яЁё]+)*$")
_VOWELS = set("aeiouyаеёиоуыэюя")


def normalize_phone(phone: str) -> str:
    digits = "".join(char for char in (phone or "") if char.isdigit())
    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("Некорректный номер телефона")
    return f"+{digits}"


def normalize_full_name(name: str) -> str:
    parts = [part for part in (name or "").strip().split() if part]
    if len(parts) < 2 or len(parts) > 4:
        raise ValueError("Укажите фамилию и имя через пробел")
    if any(not _NAME_PART.fullmatch(part) for part in parts):
        raise ValueError("Используйте только буквы: сначала фамилия, затем имя")
    if all(len(part) < 2 for part in parts) or not any(
        char.lower() in _VOWELS for part in parts for char in part
    ):
        raise ValueError("Проверьте фамилию и имя")
    normalized = " ".join(part[0].upper() + part[1:].lower() for part in parts)
    if len(normalized) > 255:
        raise ValueError("Фамилия и имя не должны превышать 255 символов")
    return normalized


def sign_client_access(user_id: int, master_id: int, bot_token: str, auth_ts: int | None = None) -> str:
    payload = f"client={int(user_id)}&master={int(master_id)}"
    if auth_ts is not None:
        payload += f"&auth_ts={int(auth_ts)}"
    return hmac.new(bot_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_client_access(
    user_id: int,
    master_id: int,
    signature: str,
    bot_token: str,
    auth_ts: int | None = None,
    require_fresh: bool = False,
) -> None:
    expected = sign_client_access(user_id, master_id, bot_token, auth_ts)
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Откройте запись через Telegram-бота мастера")
    if require_fresh:
        import time
        from backend.middleware.tg_auth import (
            LINK_TTL_SECONDS,
            LINK_EXPIRED_DETAIL,
            LINK_INVALID_DETAIL,
            _CLOCK_SKEW_SECONDS,
        )
        if auth_ts is None:
            raise HTTPException(status_code=401, detail=LINK_EXPIRED_DETAIL)
        now = int(time.time())
        if now - int(auth_ts) > LINK_TTL_SECONDS:
            raise HTTPException(status_code=401, detail=LINK_EXPIRED_DETAIL)
        if int(auth_ts) - now > _CLOCK_SKEW_SECONDS:
            raise HTTPException(status_code=401, detail=LINK_INVALID_DETAIL)


async def get_client_profile(db: AsyncSession, telegram_id: int) -> ClientProfile | None:
    result = await db.execute(select(ClientProfile).where(ClientProfile.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def save_client_profile(
    db: AsyncSession,
    telegram_id: int,
    username: str | None,
    phone: str,
    name: str,
) -> ClientProfile:
    normalized_phone = normalize_phone(phone)
    normalized_name = normalize_full_name(name)
    profile = await get_client_profile(db, telegram_id)
    if profile:
        profile.telegram_username = username or profile.telegram_username
        profile.phone = normalized_phone
        profile.name = normalized_name
    else:
        profile = ClientProfile(
            telegram_id=telegram_id,
            telegram_username=username,
            phone=normalized_phone,
            name=normalized_name,
        )
        db.add(profile)
    await db.flush()
    return profile


async def ensure_master_client(db: AsyncSession, master_id: int, profile: ClientProfile) -> Client:
    result = await db.execute(
        select(Client).where(
            Client.master_id == master_id,
            Client.telegram_id == profile.telegram_id,
        )
    )
    client = result.scalar_one_or_none()
    if client:
        client.name = profile.name
        client.phone = profile.phone
    else:
        # Привязываем зарегистрировавшегося клиента к ранее заведённой мастером
        # карточке ТОЛЬКО по телефону. Слияние по совпадению имени убрано:
        # два разных «Иванов Иван» могли присвоить друг другу историю и телефон.
        result = await db.execute(
            select(Client).where(
                Client.master_id == master_id,
                Client.telegram_id.is_(None),
                Client.phone == profile.phone,
            )
        )
        client = result.scalar_one_or_none()
        if client:
            client.telegram_id = profile.telegram_id
            client.name = profile.name
            client.phone = profile.phone
        else:
            client = Client(
                master_id=master_id,
                telegram_id=profile.telegram_id,
                name=profile.name,
                phone=profile.phone,
            )
            db.add(client)
            await db.flush()
    return client


def telegram_profile_url(telegram_id: int | None, username: str | None = None) -> str | None:
    if username:
        cleaned = username.lstrip("@").strip()
        if cleaned:
            return f"https://t.me/{cleaned}"
    return f"tg://user?id={telegram_id}" if telegram_id else None
