import time
from urllib.parse import urlencode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from backend.config import build_url, get_urls
from backend.handlers.master_bot import is_meaningful_custom_button
from backend.middleware.tg_auth import sign_auth_params

SUPERADMIN_ID = 623597334


def _signed_url(base_path: str, user_id: int | None = None, username: str | None = None, first_name: str | None = None,
                extra_params: dict | None = None) -> str:
    params = dict(extra_params or {})
    if user_id:
        auth_ts = int(time.time())
        params["user"] = user_id
        params["auth_ts"] = auth_ts
        sig = sign_auth_params(user_id, auth_ts)
        if sig:
            params["sig"] = sig
    if username:
        params["username"] = username
    if first_name:
        params["name"] = first_name
    return build_url(base_path, params)


def build_client_url(
    master_id: int | None = None,
    user_id: int | None = None,
    username: str | None = None,
    first_name: str | None = None,
) -> str:
    """Собирает URL для реальной записи к мастеру."""
    params = {}
    if master_id:
        params["master_id"] = master_id
    if user_id:
        params["user"] = user_id
    if username:
        params["username"] = username
    if first_name:
        params["name"] = first_name
    return build_url("/call", params)


def architect_menu_keyboard(user_id: int | None = None, has_bot: bool = False, has_vk_bot: bool = False) -> InlineKeyboardMarkup:
    """Главное меню Архитектора.

    has_bot=True + has_vk_bot=False → кнопка привязки VK-бота.
    has_bot=True + has_vk_bot=True  → кнопка скрыта (VK уже привязан).
    """
    btn_overview = InlineKeyboardButton(
        text="✨ Как это работает",
        callback_data="overview"
    )
    btn_create = InlineKeyboardButton(
        text="🚀 Создать своего бота",
        callback_data="create_bot"
    )
    btn_link_vk = InlineKeyboardButton(
        text="🔵 Привязать своего бота ВКонтакте",
        callback_data="link_vk_bot"
    )
    btn_demo = InlineKeyboardButton(
        text="👁 Посмотреть демо",
        callback_data="demo_menu"
    )
    btn_subscription = InlineKeyboardButton(
        text="💳 Подписка",
        callback_data="subscription"
    )
    btn_settings = InlineKeyboardButton(
        text="⚙️ Настройки",
        callback_data="settings_menu"
    )
    btn_delete = InlineKeyboardButton(
        text="🗑 Удалить бота",
        callback_data="delete_bot_menu"
    )
    btn_feedback = InlineKeyboardButton(
        text="💬 Обратная связь с командой разработчиков",
        callback_data="feedback"
    )

    keyboard = [
        [btn_overview],
        [btn_demo],
        [btn_create],
    ]
    if has_bot and not has_vk_bot:
        keyboard.append([btn_link_vk])
    keyboard += [
        [btn_subscription],
    ]
    # «Настройки» (уведомления, инфо о боте) показываем только владельцу бота —
    # раньше этот экран существовал в коде, но в меню на него не вело ничего.
    if has_bot:
        keyboard.append([btn_settings])
    keyboard += [
        [btn_feedback],
        [btn_delete],
    ]

    # Superadmin button - only for id 623597334
    if user_id == SUPERADMIN_ID:
        keyboard.append([
            InlineKeyboardButton(
                text="📊 Админка",
                url=build_superadmin_url(user_id)
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню с корректно вычисленным состоянием (есть ли бот / привязан ли ВК).

    Единая точка сборки: используется во всех обработчиках «Назад в меню», чтобы
    кнопка «Привязать бота ВКонтакте» не появлялась у уже привязанного аккаунта.
    """
    has_bot = await owner_has_bot(user_id)
    has_vk_bot = await owner_has_vk_bot(user_id) if has_bot else False
    return architect_menu_keyboard(user_id=user_id, has_bot=has_bot, has_vk_bot=has_vk_bot)


async def owner_has_bot(telegram_id: int) -> bool:
    """True, если у мастера уже есть Telegram-бот (значит можно привязать ВК)."""
    from architect.services.bot_manager import bot_manager
    try:
        return await bot_manager.get_bot_status(telegram_id) is not None
    except Exception:
        return False


async def owner_has_vk_bot(telegram_id: int) -> bool:
    """True, если все Telegram-боты владельца уже имеют VK-пару."""
    from architect.services.vk_bot_manager import vk_bot_manager
    try:
        existing = await vk_bot_manager.get_vk_bot(telegram_id)
        if not existing:
            return False
        return not await vk_bot_manager.get_unlinked_telegram_bots(telegram_id)
    except Exception:
        return False


def demo_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню демо-режима"""
    btn_master = InlineKeyboardButton(
        text="👨‍💼 Я мастер",
        callback_data="demo_master"
    )
    btn_client = InlineKeyboardButton(
        text="👤 Я клиент",
        callback_data="demo_client"
    )
    btn_back = InlineKeyboardButton(
        text="◀ Назад",
        callback_data="back_to_menu"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_master],
        [btn_client],
        [btn_back],
    ])


def build_admin_url(user_id: int | None = None, username: str | None = None, first_name: str | None = None) -> str:
    """Собирает URL для реальной админки мастера."""
    return _signed_url("/calendar", user_id, username, first_name)


def build_superadmin_url(user_id: int | None = None, username: str | None = None, first_name: str | None = None) -> str:
    """Собирает URL для супер-админки."""
    return _signed_url("/superadmin", user_id, username, first_name)


def demo_master_keyboard(user_id: int | None = None, username: str | None = None, first_name: str | None = None) -> InlineKeyboardMarkup:
    """Клавиатура демо-режима для мастера"""
    admin_url = _signed_url("/calendar", user_id, username, first_name, {
        "demo": "1",
    })
    btn_calendar = InlineKeyboardButton(
        text="📅 Календарь",
        url=admin_url
    )
    btn_bookings = InlineKeyboardButton(
        text="📋 Мои записи",
        callback_data="demo_bookings"
    )
    btn_back = InlineKeyboardButton(
        text="◀ Выйти из демо",
        callback_data="demo_menu"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_calendar],
        [btn_bookings],
        [btn_back],
    ])


def demo_client_keyboard(user_id: int | None = None, username: str | None = None, first_name: str | None = None) -> InlineKeyboardMarkup:
    """Клавиатура демо-режима для клиента"""
    demo_client_url = build_url("/call", {
        "demo": "1",
        "user": user_id,
        "username": username,
        "name": first_name,
    })
    btn_book = InlineKeyboardButton(
        text="📅 Записаться",
        url=demo_client_url
    )
    btn_price = InlineKeyboardButton(
        text="💰 Прайс",
        callback_data="demo_price"
    )
    btn_faq = InlineKeyboardButton(
        text="❓ FAQ",
        callback_data="demo_faq"
    )
    btn_address = InlineKeyboardButton(
        text="📍 Адрес",
        callback_data="demo_address"
    )
    btn_portfolio = InlineKeyboardButton(
        text="🎨 Портфолио",
        callback_data="demo_portfolio"
    )
    btn_back = InlineKeyboardButton(
        text="◀ Выйти из демо",
        callback_data="demo_menu"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_book],
        [btn_price],
        [btn_faq],
        [btn_address],
        [btn_portfolio],
        [btn_back],
    ])


def demo_client_keyboard_dynamic(menu_data: dict, user_id: int | None = None, username: str | None = None, first_name: str | None = None) -> InlineKeyboardMarkup:
    """
    Динамическая клавиатура для клиента на основе настроек из админки.
    menu_data = {
        "price": {"active": True, "content": {...}},
        "faq": {"active": True, "content": {...}},
        ...
    }
    user_id, username, first_name — данные пользователя для передачи в URL записи.
    """
    keyboard = []

    # Кнопка записи (всегда) - URL с параметрами пользователя
    demo_client_url = build_url("/call", {
        "demo": "1",
        "user": user_id,
        "username": username,
        "name": first_name,
    })
    keyboard.append([
        InlineKeyboardButton(
            text="📅 Записаться",
            url=demo_client_url
        )
    ])

    # Кнопки на основе активных настроек (ТОЛЬКО если active: True)
    if menu_data.get("price", {}).get("active", False):
        keyboard.append([
            InlineKeyboardButton(
                text="💰 Прайс",
                callback_data="demo_menu_button:price"
            )
        ])

    if menu_data.get("faq", {}).get("active", False):
        keyboard.append([
            InlineKeyboardButton(
                text="❓ FAQ",
                callback_data="demo_menu_button:faq"
            )
        ])

    if menu_data.get("address", {}).get("active", False):
        keyboard.append([
            InlineKeyboardButton(
                text="📍 Адрес",
                callback_data="demo_menu_button:address"
            )
        ])

    if menu_data.get("portfolio", {}).get("active", False):
        keyboard.append([
            InlineKeyboardButton(
                text="🎨 Портфолио",
                callback_data="demo_menu_button:portfolio"
            )
        ])

    # Кастомные кнопки (до 3 штук)
    custom_data = menu_data.get("custom", {})
    custom_content = custom_data.get("content", {}) if isinstance(custom_data, dict) else {}
    custom_buttons = custom_content.get("custom_buttons", []) or custom_data.get("custom_buttons", [])
    for i, btn in enumerate(custom_buttons):
        if not btn.get("active", False) or not is_meaningful_custom_button(btn):
            continue
        name = btn.get("name", "ℹ️ Информация")
        icon = btn.get("icon", "")
        # Format: "🔸 Название" or just "Название"
        button_text = f"{icon} {name}".strip() if icon else name
        keyboard.append([
            InlineKeyboardButton(
                text=button_text[:64],  # Telegram limit
                callback_data=f"demo_menu_button:custom:{i}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="◀ Выйти из демо",
            callback_data="demo_menu"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def is_visible_menu_button(button: dict) -> bool:
    """Show ONLY active buttons - ignore content."""
    return bool(button.get("active", False))
