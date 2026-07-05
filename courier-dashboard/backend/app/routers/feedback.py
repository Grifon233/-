"""POST /feedback — обратная связь из приложения, падает владельцу в Telegram.

Фронт шлёт {text, city, source}. Backend отправляет сообщение боту-отправителю
(FEEDBACK_BOT_TOKEN) в чат владельца (FEEDBACK_CHAT_ID = 623597334).
Если токен не задан — возвращаем sent=false с понятной причиной (фронт это покажет).
"""
import logging
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)
_requests: dict[str, deque[float]] = defaultdict(deque)


class Feedback(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    city: str | None = None
    source: str | None = None   # напр. "miniapp"
    user: str | None = None     # username/id отправителя, если известен


@router.post("/feedback")
async def feedback(fb: Feedback, request: Request) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = _requests[client_ip]
    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= settings.feedback_rate_limit:
        return {"sent": False, "reason": "rate_limited"}
    recent.append(now)

    if not settings.feedback_bot_token:
        return {"sent": False, "reason": "feedback_bot_not_configured"}

    parts = ["🛠 Обратная связь из приложения «Курьеры»"]
    if fb.city:
        parts.append(f"Город: {fb.city}")
    if fb.user:
        parts.append(f"От: {fb.user}")
    if fb.source:
        parts.append(f"Источник: {fb.source}")
    parts.append("")
    parts.append(fb.text)
    message = "\n".join(parts)

    url = f"https://api.telegram.org/bot{settings.feedback_bot_token}/sendMessage"
    payload = {"chat_id": settings.feedback_chat_id, "text": message}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload)
        if r.status_code == 200:
            try:
                if r.json().get("ok"):
                    return {"sent": True}
            except (ValueError, TypeError, AttributeError):
                logger.warning("Telegram feedback returned invalid JSON")
        logger.warning("Telegram feedback error: status=%s", r.status_code)
        return {"sent": False, "reason": "telegram_error"}
    except httpx.HTTPError:
        logger.exception("Telegram feedback request failed")
        return {"sent": False, "reason": "request_failed"}
