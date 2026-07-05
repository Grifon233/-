"""Подпись и проверка VK-идентичности клиента для ссылки записи.

Зеркало backend/client_profiles.sign_client_access, но для VK ID. Ключом
подписи служит токен сообщества (как и в Telegram — токен бота).
"""
import hashlib
import hmac

from fastapi import HTTPException


def sign_vk_client_access(vk_id: int, master_id: int, token: str, auth_ts: int | None = None) -> str:
    payload = f"vk={int(vk_id)}&master={int(master_id)}"
    if auth_ts is not None:
        payload += f"&auth_ts={int(auth_ts)}"
    return hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_vk_client_access(
    vk_id: int,
    master_id: int,
    signature: str,
    token: str,
    auth_ts: int | None = None,
    require_fresh: bool = False,
) -> None:
    expected = sign_vk_client_access(vk_id, master_id, token, auth_ts)
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Откройте запись через бота ВКонтакте")
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
