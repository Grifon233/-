"""
Единый конфиг URL для Master Booking.
Все публичные URL берутся отсюда — никакого хардкода доменов.
"""
import os
from functools import lru_cache
from pathlib import Path


@lru_cache()
def get_urls() -> dict:
    """Единый источник публичных URL.

    WEB_URL — адрес фронтенда (для ссылок /call, /calendar).
    WEBHOOK_BASE_URL — адрес куда Telegram шлёт webhook.
    WEBHOOK_PATH — путь webhook на backend. По умолчанию /api/webhook,
    потому что production nginx обычно проксирует /api в FastAPI.
    Если WEBHOOK_BASE_URL не задан, используется WEB_URL (для dev).
    """
    web_url = (os.getenv("WEB_URL") or "").rstrip("/")
    if not web_url:
        web_url = "https://xn----7sbbjnkdfkb7a4a1a.online"

    webhook_base = (os.getenv("WEBHOOK_BASE_URL") or "").rstrip("/")
    if not webhook_base:
        webhook_base = web_url

    webhook_path = (os.getenv("WEBHOOK_PATH") or "/api/webhook").strip()
    if not webhook_path.startswith("/"):
        webhook_path = f"/{webhook_path}"
    webhook_path = webhook_path.rstrip("/")

    return {
        "WEB_URL": web_url,
        "WEBHOOK_BASE_URL": webhook_base,
        "WEBHOOK_PATH": webhook_path,
    }


def build_url(path: str, params: dict | None = None) -> str:
    """Построить полный URL к фронтенду."""
    from urllib.parse import urlencode
    base = get_urls()["WEB_URL"]
    url = f"{base}{path}"
    if params:
        filtered = {k: v for k, v in params.items() if v is not None}
        if filtered:
            url += "?" + urlencode(filtered)
    return url


def get_webhook_url(token: str) -> str:
    """URL для webhook бота на сервере."""
    urls = get_urls()
    return f"{urls['WEBHOOK_BASE_URL']}{urls['WEBHOOK_PATH']}/{token}"
