"""
Демо-режим внутри Архитектора.
Показывает функционал Я мастер / Я клиент.
Динамически читает настройки меню из API.
"""
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from architect.keyboards.menu import (
    demo_menu_keyboard,
    demo_master_keyboard,
    demo_client_keyboard_dynamic,
    is_visible_menu_button,
)
from architect.config import settings
from backend.handlers.master_bot import is_meaningful_custom_button, get_custom_button_items

router = Router()


async def _safe_edit_text(message, *args, **kwargs) -> None:
    """edit_text, не падающий на «message is not modified» (повторное нажатие кнопки)."""
    try:
        await message.edit_text(*args, **kwargs)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


@router.callback_query(F.data == "demo_menu")
async def show_demo_menu(callback: CallbackQuery):
    """Показать меню демо"""
    await callback.message.edit_text(
        "👁 Демо-режим\n\n"
        "Выберите режим для просмотра:",
        reply_markup=demo_menu_keyboard()
    )
    await callback.answer()


# ================== DEMO MASTER MODE ==================

@router.callback_query(F.data == "demo_master")
async def demo_master(callback: CallbackQuery):
    """Демо режим для мастера — открывает админку"""
    user = callback.from_user
    await callback.message.edit_text(
        "👨‍💼 Демо — Режим мастера\n\n"
        "Нажмите «Календарь», чтобы посмотреть админку и готовые настройки.\n"
        "Редактирование демо сейчас выключено — данные доступны только для просмотра.",
        reply_markup=demo_master_keyboard(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name
        )
    )
    await callback.answer()


@router.callback_query(F.data == "demo_calendar")
async def demo_calendar(callback: CallbackQuery):
    """Демо календаря — legacy callback на случай старых сообщений."""
    from backend.config import build_url

    user = callback.from_user
    admin_url = build_url("/calendar", {
        "demo": "1",
        "user": user.id,
        "username": user.username,
        "name": user.first_name,
    })
    await callback.message.edit_text(
        "📅 Календарь записей\n\n"
        "Открываю админ-панель с календарём...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📅 Открыть календарь",
                url=admin_url
            )],
            [InlineKeyboardButton(
                text="◀ Назад",
                callback_data="demo_master"
            )],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "demo_bookings")
async def demo_bookings(callback: CallbackQuery):
    """Показывает расписание на сегодня"""
    from datetime import date

    today = date.today()
    bookings = await get_bookings_for_date(today)

    if not bookings:
        text = f"📅 {today.strftime('%d.%m.%Y')}\n\nЗаписей на сегодня нет"
    else:
        lines = [f"📅 {today.strftime('%d.%m.%Y')} ({len(bookings)} записей)\n"]
        for b in bookings:
            time_str = b.get("time", "")[:5]
            client = b.get("client", {})
            name = client.get("name", "Клиент")
            service = b.get("service_name") or "—"
            lines.append(f"\n🕐 {time_str}\n👤 {name}\n📌 {service}")
        text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="demo_master")],
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ================== DEMO CLIENT MODE ==================

@router.callback_query(F.data == "demo_client")
async def demo_client(callback: CallbackQuery):
    """Демо режима для клиента — показывает динамическое меню"""
    menu_data = await get_menu_buttons()

    # Передаём данные пользователя для формирования ссылки с авторизацией
    keyboard = demo_client_keyboard_dynamic(
        menu_data,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name
    )

    # Получаем имя мастера
    master = await get_master()
    master_name = master.get("name", "Мастер")

    await callback.message.edit_text(
        f"👤 {master_name}\n\n"
        "Добро пожаловать! Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("demo_menu_button:"))
async def demo_menu_button(callback: CallbackQuery):
    """Показать любую активную клиентскую кнопку из настроек мастера."""
    button_type = callback.data.split(":", 1)[1]
    buttons = await get_menu_buttons()
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name

    # Обработка кастомных кнопок с индексом (demo_menu_button:custom:0)
    if button_type.startswith("custom:"):
        try:
            custom_idx = int(button_type.split(":")[1])
        except (IndexError, ValueError):
            await callback.answer("Кнопка не найдена", show_alert=True)
            return
        custom_data = buttons.get("custom", {})
        custom_button = get_custom_button_items(custom_data.get("content", {}) or custom_data)
        if custom_idx < len(custom_button):
            btn = custom_button[custom_idx]
            if not btn.get("active", False) or not is_meaningful_custom_button(btn):
                await callback.answer("Кнопка сейчас выключена", show_alert=True)
                return
            keyboard = demo_client_keyboard_dynamic(buttons, user_id, username, first_name)
            name = btn.get("name", "Информация")
            icon = btn.get("icon", "")
            title = f"{icon} {name}".strip() if icon else name
            texts = [t for t in btn.get("texts", []) if t]
            if not texts and btn.get("text"):
                texts = [btn.get("text")]
            links = [link for link in (btn.get("links") or []) if link.get("url")]
            if not links and btn.get("url"):
                links = [{"text": btn.get("url"), "url": btn.get("url")}]
            photos = [p for p in btn.get("photos", []) if p]

            parts = [f"📋 {title}"]
            for t in texts:
                if t:
                    parts.append(t)
            for link in links:
                label = link.get("text") or link.get("url")
                parts.append(f"🔗 {label}: {link.get('url')}")
            if len(parts) == 1:
                parts.append("Информация пока не добавлена")

            await send_content_with_photos(
                callback,
                text="\n\n".join(parts),
                photos=photos,
                keyboard=keyboard,
            )
        else:
            await callback.answer("Кнопка не найдена", show_alert=True)
        await callback.answer()
        return

    button = buttons.get(button_type, {})

    if not is_visible_menu_button(button):
        await callback.answer("Кнопка сейчас выключена", show_alert=True)
        return

    content = button.get("content", {}) or {}
    keyboard = demo_client_keyboard_dynamic(buttons, user_id, username, first_name)

    if button_type == "price":
        await _safe_edit_text(callback.message, build_price_text(content), reply_markup=keyboard)
    elif button_type == "faq":
        await _safe_edit_text(callback.message, build_faq_text(content), reply_markup=keyboard)
    elif button_type == "address":
        await send_content_with_photos(
            callback,
            text=content.get("text") or "📍 Адрес\n\nАдрес пока не указан",
            photos=[content.get("photo")] if content.get("photo") else [],
            keyboard=keyboard,
        )
    elif button_type == "portfolio":
        photos = [photo for photo in content.get("photos", []) if photo]
        await send_content_with_photos(
            callback,
            text="🎨 Портфолио",
            photos=photos,
            keyboard=keyboard,
            empty_text="🎨 Портфолио\n\nФото пока не добавлены",
        )
    elif button_type == "custom":
        await send_custom_content(callback, content, keyboard)
    else:
        await callback.answer("Неизвестная кнопка", show_alert=True)
        return

    await callback.answer()


@router.callback_query(F.data == "demo_price")
async def demo_price(callback: CallbackQuery):
    """Демо прайса — берёт данные из БД через API"""
    buttons = await get_menu_buttons()
    content = buttons.get("price", {}).get("content", {})

    menu_data = await get_menu_buttons()
    keyboard = demo_client_keyboard_dynamic(menu_data, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)

    await callback.message.edit_text(build_price_text(content), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "demo_faq")
async def demo_faq(callback: CallbackQuery):
    """Демо FAQ — берёт данные из БД через API"""
    buttons = await get_menu_buttons()
    content = buttons.get("faq", {}).get("content", {})

    menu_data = await get_menu_buttons()
    keyboard = demo_client_keyboard_dynamic(menu_data, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)

    await callback.message.edit_text(build_faq_text(content), reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "demo_address")
async def demo_address(callback: CallbackQuery):
    """Демо адреса — берёт данные из БД через API"""
    buttons = await get_menu_buttons()
    content = buttons.get("address", {}).get("content", {})
    menu_data = await get_menu_buttons()
    keyboard = demo_client_keyboard_dynamic(menu_data, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)

    await send_content_with_photos(
        callback,
        text=content.get("text") or "📍 Адрес\n\nАдрес пока не указан",
        photos=[content.get("photo")] if content.get("photo") else [],
        keyboard=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "demo_portfolio")
async def demo_portfolio(callback: CallbackQuery):
    """Демо портфолио — берёт данные из БД через API"""
    buttons = await get_menu_buttons()
    content = buttons.get("portfolio", {}).get("content", {})
    photos = content.get("photos", [])

    menu_data = await get_menu_buttons()
    keyboard = demo_client_keyboard_dynamic(menu_data, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)

    await send_content_with_photos(
        callback,
        text="🎨 Портфолио",
        photos=[photo for photo in photos if photo],
        keyboard=keyboard,
        empty_text="🎨 Портфолио\n\nФото пока не добавлены",
    )
    await callback.answer()


@router.callback_query(F.data == "demo_custom")
async def demo_custom(callback: CallbackQuery):
    """Демо кастомной кнопки — показывает текст из настроек"""
    buttons = await get_menu_buttons()
    content = buttons.get("custom", {}).get("content", {})

    menu_data = await get_menu_buttons()
    keyboard = demo_client_keyboard_dynamic(menu_data, callback.from_user.id, callback.from_user.username, callback.from_user.first_name)

    await send_custom_content(callback, content, keyboard)
    await callback.answer()


# ================== HELPERS ==================

async def get_bookings_for_date(booking_date):
    """Получить демо-записи на конкретную дату из изолированного demo API."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            date_str = booking_date.isoformat() if hasattr(booking_date, 'isoformat') else str(booking_date)
            response = await client.get(
                f"{settings.api_url}/api/demo/bookings/master",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                bookings = data.get("data", {}).get("bookings", [])
                return [b for b in bookings if b.get("date") == date_str]
    except Exception:
        pass
    return []


async def get_master():
    """Получить данные демо-мастера из API."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_url}/api/demo/master",
                timeout=10
            )
            if response.status_code == 200:
                return response.json().get("data", {})
    except Exception:
        pass
    return {"name": "Мастер"}


async def get_menu_buttons():
    """Получить настройки кнопок меню демо-мастера из API."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_url}/api/demo/menu-buttons",
                timeout=10
            )
            if response.status_code == 200:
                return response.json().get("data", {}).get("buttons", {})
    except Exception:
        pass
    return {}


def build_price_text(content: dict) -> str:
    items = content.get("items", [])
    if items and any(item.get("name") for item in items):
        lines = [
            f"{i + 1}. {item.get('name', '')} — {item.get('price', '')}"
            for i, item in enumerate(items)
            if item.get("name")
        ]
        return "💰 Прайс-лист:\n\n" + "\n".join(lines)
    return "💰 Прайс-лист\n\nМастер пока не добавил услуги"


def build_faq_text(content: dict) -> str:
    items = content.get("items", [])
    if items and any(item.get("question") for item in items):
        lines = []
        for i, item in enumerate(items):
            if item.get("question"):
                lines.append(f"{i + 1}. ❓ {item.get('question', '')}")
                if item.get("answer"):
                    lines.append(f"   💬 {item.get('answer', '')}")
        return "❓ Частые вопросы:\n\n" + "\n".join(lines)
    return "❓ Частые вопросы\n\nМастер пока не добавил вопросы"


def normalize_photo_url(photo_url: str | None) -> str | None:
    if not photo_url:
        return None
    if photo_url.startswith("/uploads/"):
        photo_url = f"/api{photo_url}"
    if photo_url.startswith("/"):
        return f"{settings.api_url.rstrip('/')}{photo_url}"
    return photo_url


async def load_photo(photo_url: str) -> BufferedInputFile | str:
    import httpx
    from pathlib import PurePosixPath
    from urllib.parse import unquote, urlsplit

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        response = await client.get(photo_url)
        response.raise_for_status()

    filename = unquote(PurePosixPath(urlsplit(photo_url).path).name) or "photo.jpg"
    return BufferedInputFile(response.content, filename=filename)


async def send_content_with_photos(
    callback: CallbackQuery,
    text: str,
    photos: list[str],
    keyboard: InlineKeyboardMarkup,
    empty_text: str | None = None,
) -> None:
    normalized_photos = [url for url in (normalize_photo_url(photo) for photo in photos) if url]

    if not normalized_photos:
        await _safe_edit_text(callback.message, empty_text or text, reply_markup=keyboard)
        return

    await callback.message.answer(text)
    for index, photo_url in enumerate(normalized_photos[:10]):
        try:
            photo = await load_photo(photo_url)
            await callback.message.answer_photo(photo=photo)
        except Exception:
            await callback.message.answer(f"Фото: {photo_url}")
    await callback.message.answer("Выберите действие:", reply_markup=keyboard)


async def send_custom_content(
    callback: CallbackQuery,
    content: dict,
    keyboard: InlineKeyboardMarkup,
) -> None:
    custom_buttons = get_custom_button_items(content)
    item = custom_buttons[0] if custom_buttons else content

    name = item.get("name", "Информация")
    texts = [text for text in item.get("texts", []) if text]
    if not texts and item.get("text"):
        texts = [item.get("text")]
    links = [link for link in (item.get("links") or []) if link.get("url")]
    if not links and item.get("url"):
        links = [{"text": item.get("url"), "url": item.get("url")}]
    photos = [photo for photo in item.get("photos", []) if photo]

    parts = [f"📋 {name}"]
    if texts:
        parts.append("\n\n".join(texts))
    if links:
        parts.append("\n".join(f"🔗 {link.get('text') or link['url']}: {link['url']}" for link in links))
    if len(parts) == 1:
        parts.append("Информация пока не добавлена")

    await send_content_with_photos(
        callback,
        text="\n\n".join(parts),
        photos=photos,
        keyboard=keyboard,
    )
