"""POST /feedback — отправка сообщения в настроенный Telegram-чат."""
import logging
import re
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)
_requests: dict[str, deque[float]] = defaultdict(deque)
_global_requests: deque[float] = deque()


class _RedactTelegramToken(logging.Filter):
    _url = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._url.sub(r"\1[redacted]", message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


# HTTPX пишет полный URL в INFO даже при успешном ответе Telegram.
logging.getLogger("httpx").addFilter(_RedactTelegramToken())


class Feedback(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=2000)
    city: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=100)


def _expire(times: deque[float], now: float) -> None:
    while times and times[0] <= now - 60:
        times.popleft()


def _allow_request(client_ip: str, now: float) -> bool:
    _expire(_global_requests, now)
    if len(_global_requests) >= settings.feedback_global_rate_limit:
        return False
    for addr, times in list(_requests.items()):
        _expire(times, now)
        if not times:
            _requests.pop(addr)
    recent = _requests[client_ip]
    if len(recent) >= settings.feedback_rate_limit:
        return False
    recent.append(now)
    _global_requests.append(now)
    return True


@router.post("/feedback")
async def feedback(fb: Feedback, request: Request) -> dict:
    if not (settings.feedback_bot_token and settings.feedback_chat_id):
        return {"sent": False, "reason": "feedback_bot_not_configured"}

    client_ip = request.client.host if request.client else "unknown"
    if not _allow_request(client_ip, time.monotonic()):
        return {"sent": False, "reason": "rate_limited"}

    parts = ["🛠 Обратная связь из приложения «Курьеры»"]
    if fb.city:
        parts.append("Город: " + " ".join(fb.city.split()))
    if fb.source:
        parts.append("Источник: " + " ".join(fb.source.split()))
    parts.append("")
    parts.append(fb.text)

    # Токен находится в URL: не логируем объект httpx-ошибки/URL или сырой ответ.
    url = f"https://api.telegram.org/bot{settings.feedback_bot_token}/sendMessage"
    payload = {"chat_id": settings.feedback_chat_id, "text": "\n".join(parts), "link_preview_options": {"is_disabled": True}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
        if response.status_code == 200:
            try:
                result = response.json()
                if isinstance(result, dict) and result.get("ok") is True:
                    return {"sent": True}
            except (ValueError, RecursionError):
                logger.warning("Telegram feedback returned invalid JSON")
        logger.warning("Telegram feedback error: status=%s", response.status_code)
        return {"sent": False, "reason": "telegram_error"}
    except httpx.HTTPError as exc:
        logger.warning("Telegram feedback request failed (%s)", type(exc).__name__)
        return {"sent": False, "reason": "request_failed"}
