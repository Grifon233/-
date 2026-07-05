"""
API service для получения данных о мастере и меню.
Используется в демо-режиме.
"""
import httpx
from architect.config import settings


async def get_master():
    """Получить данные мастера"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_url}/api/admin/master",
                timeout=10
            )
            if response.status_code == 200:
                return response.json().get("data", {})
    except Exception:
        pass
    return {"name": "Мастер Демо"}


async def get_menu_buttons():
    """Получить настройки кнопок меню"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_url}/api/admin/menu-buttons",
                timeout=10
            )
            if response.status_code == 200:
                return response.json().get("data", {}).get("buttons", {})
    except Exception:
        pass
    return {}