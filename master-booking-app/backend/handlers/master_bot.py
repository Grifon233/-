import logging
from datetime import date
import hashlib
import hmac
from html import escape
import os
from urllib.parse import urlencode
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, KeyboardButtonRequestUser, BufferedInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from backend.database import async_session_maker, MasterBot, Master, Client, Booking, MenuButton
from backend.client_profiles import get_client_profile, normalize_full_name, normalize_phone, save_client_profile, sign_client_access, telegram_profile_url, ensure_master_client
from backend.config import build_url, get_urls
from backend.media_storage import normalize_media_reference
from backend.token_utils import mask_token
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = Router()

# Кэш «raw token → bot_id»: get_master_info вызывается на каждое входящее сообщение,
# и раньше расшифровывал токены ВСЕХ ботов каждый раз. Кэш убирает этот перебор;
# статус/данные мастера всё равно перечитываются из БД свежими.
import time as _time
_TOKEN_BOT_CACHE: dict[str, tuple[int, float]] = {}
_TOKEN_BOT_CACHE_TTL = 300
ARCHITECT_BOT_URL = "https://t.me/SoftwareArchitects_bot"
PLACEHOLDER_CUSTOM_NAMES = {"Напишите своё название", "Название кнопки", "Информация"}
CLIENT_HELP_TEXT = (
    "ℹ️ <b>Как использовать бота</b>\n\n"
    "1. Чтобы записаться, нажмите кнопку «Записаться» и перейдите на сайт. В календаре выберите дату, "
    "затем подходящее свободное время. При необходимости оставьте комментарий и нажмите «Записаться». "
    "После этого мастер получит уведомление о вашей записи.\n\n"
    "2. Авторизация на сайте происходит автоматически через Telegram-аккаунт, из которого вы перешли. "
    "К записи для мастера прикрепляются ваши фамилия, имя и номер телефона, указанные при первом входе в бота.\n\n"
    "3. Если дата в календаре неактивна, запись на неё ещё не открыта или этот день недоступен для записи.\n\n"
    "4. По умолчанию запись создаётся на ваши данные. Если вы хотите записать другого человека, укажите "
    "в комментарии его имя, телефон и ссылку на Telegram-профиль, если считаете это необходимым."
)


class ClientRegistration(StatesGroup):
    waiting_for_contact = State()
    waiting_for_full_name = State()


def sign_auth_params(user_id: int, auth_ts: int | None = None) -> str | None:
    secret = os.getenv("AUTH_SIGNING_SECRET") or os.getenv("ARCHITECT_TOKEN")
    if not secret:
        return None
    payload = f"user={int(user_id)}"
    if auth_ts is not None:
        payload += f"&auth_ts={int(auth_ts)}"
    payload = payload.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


async def get_master_info(token: str, user_telegram_id: int) -> tuple[dict | None, bool]:
    """Получает информацию о мастере по токену бота.
    Возвращает (None, False) если бот заморожен/остановлен."""
    from backend.token_utils import decrypt_token

    allowed_statuses = ["running", "error", "frozen", "stopped", "crashed"]

    async with async_session_maker() as session:
        bot = None
        # Быстрый путь: берём bot_id из кэша и подтверждаем одним decrypt.
        cached = _TOKEN_BOT_CACHE.get(token)
        if cached and _time.time() - cached[1] < _TOKEN_BOT_CACHE_TTL:
            candidate = await session.get(MasterBot, cached[0])
            if candidate and candidate.status in allowed_statuses and decrypt_token(candidate.token) == token:
                bot = candidate
            else:
                _TOKEN_BOT_CACHE.pop(token, None)

        # Медленный путь: перебор с расшифровкой (наполняет кэш).
        if bot is None:
            result = await session.execute(
                select(MasterBot).where(MasterBot.status.in_(allowed_statuses))
            )
            for b in result.scalars().all():
                if decrypt_token(b.token) == token:
                    bot = b
                    _TOKEN_BOT_CACHE[token] = (b.id, _time.time())
                    break

        if not bot:
            return None, False

        # MASTER_BOT_STATUS — единый набор статусов:
        # running, error, frozen, stopped, crashed
        if bot.status in ("frozen", "stopped", "error", "crashed"):
            logger.warning(f"Blocked access to {bot.status} bot token={mask_token(token)}")
            return None, False

        master = await session.get(Master, bot.master_id) if getattr(bot, "master_id", None) else None
        if not master:
            result = await session.execute(select(Master).where(Master.telegram_id == bot.master_telegram_id))
            master = result.scalar_one_or_none()
            if master and bot.master_id != master.id:
                bot.master_id = master.id
                await session.commit()
        if not master:
            master = Master(
                telegram_id=bot.master_telegram_id,
                name="Мастер",
                is_demo=False,
                use_services=False,
                interval_minutes=60,
            )
            session.add(master)
            await session.flush()
            bot.master_id = master.id
            await session.commit()
            await session.refresh(master)
            logger.warning(f"Created missing master profile for bot owner {bot.master_telegram_id}")

        # Админ — именно владелец MasterBot. Это надёжнее, чем сверка с Master.telegram_id.
        is_admin = user_telegram_id == bot.master_telegram_id

        return {
            "id": master.id,
            "name": master.name,
            "telegram_id": master.telegram_id,
            "token": token,
            "bot_id": bot.id,
        }, is_admin


async def build_menu(master_id: int, is_admin: bool, bot_token: str = None, user: object | None = None, bot_username: str = None, bot_id: int | None = None) -> InlineKeyboardMarkup:
    """Генерирует меню для бота"""
    buttons = []

    if is_admin:
        # Админские кнопки - каждая на отдельной строке
        admin_params = {
            "user": user.id if user else None,
            "master_id": master_id,
            "bot_id": bot_id,
            "username": getattr(user, "username", None) if user else None,
            "name": getattr(user, "first_name", None) if user else None,
        }
        if user:
            import time as _time
            auth_ts = int(_time.time())
            admin_params["auth_ts"] = auth_ts
            sig = sign_auth_params(user.id, auth_ts)
            if sig:
                admin_params["sig"] = sig
        buttons.append([InlineKeyboardButton(text="📅 Календарь", url=build_url("/calendar", admin_params))])
        buttons.append([InlineKeyboardButton(text="📋 Мои записи", callback_data="my_bookings")])
        if bot_username:
            bot_url = f"https://t.me/{bot_username}"
            share_url = "https://t.me/share/url?" + urlencode({
                "url": bot_url,
                "text": "Вы можете записаться ко мне через этого бота.",
            })
            buttons.append([InlineKeyboardButton(text="📤 Поделиться ссылкой на бота", url=share_url)])
            buttons.append([InlineKeyboardButton(text="🔗 Создать URL-ссылку на вашего бота", callback_data="bot_url")])
    else:
        # Клиентские кнопки
        client_params = {"master_id": master_id, "bot_id": bot_id}
        if user and bot_token:
            import time as _time
            client_auth_ts = int(_time.time())
            client_params.update({
                "user": getattr(user, "id", None),
                "auth_ts": client_auth_ts,
                "client_sig": sign_client_access(user.id, master_id, bot_token, client_auth_ts),
                "username": getattr(user, "username", None),
                "name": getattr(user, "first_name", None),
            })
        buttons.append([InlineKeyboardButton(
            text="📅 Записаться",
            url=build_url("/call", client_params)
        )])

        # Дополнительные кнопки из MenuButton (если есть)
        async with async_session_maker() as session:
            result = await session.execute(
                select(MenuButton).where(
                    MenuButton.master_id == master_id,
                )
            )
            menu_buttons = result.scalars().all()
            for btn in menu_buttons:
                if not is_visible_menu_button_record(btn):
                    continue
                if btn.button_type == "price":
                    buttons.append([InlineKeyboardButton(text="💰 Прайс", callback_data="menu:price")])
                elif btn.button_type == "faq":
                    buttons.append([InlineKeyboardButton(text="❓ FAQ", callback_data="menu:faq")])
                elif btn.button_type == "address":
                    buttons.append([InlineKeyboardButton(text="📍 Адрес", callback_data="menu:address")])
                elif btn.button_type == "portfolio":
                    buttons.append([InlineKeyboardButton(text="🎨 Портфолио", callback_data="menu:portfolio")])
                elif btn.button_type == "custom":
                    content = btn.content_json or {}
                    for idx, item in enumerate(get_custom_button_items(content)):
                        if item.get("active") and is_meaningful_custom_button(item):
                            name = item.get("name", "Информация")
                            icon = item.get("icon", "")
                            text = f"{icon} {name}".strip() if icon else name
                            buttons.append([InlineKeyboardButton(text=text[:64], callback_data=f"menu:custom:{idx}")])
        buttons.append([InlineKeyboardButton(text="ℹ️ Как использовать бота", callback_data="client_help")])
        buttons.append([InlineKeyboardButton(text="🤖 Хочу себе такого же бота", url=ARCHITECT_BOT_URL)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def ask_for_contact(message: Message, state: FSMContext) -> None:
    await state.set_state(ClientRegistration.waiting_for_contact)
    await message.answer(
        "Чтобы запись прошла спокойно и без ошибок, поделитесь номером телефона кнопкой ниже.\n\n"
        "Номер нужен только для связи по вашей записи. Вводить его вручную не потребуется.",
        reply_markup=contact_keyboard(),
    )


def booking_card_text(booking: Booking, client: Client, index: int | None = None, profile_url: str | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    time_text = booking.time.strftime("%H:%M") if hasattr(booking.time, "strftime") else str(booking.time)[:5]
    lines = [
        f"{prefix}<b>{time_text}</b> — {escape(client.name)}",
        f"📱 {escape(client.phone or 'Телефон не указан')}",
    ]
    if not profile_url:
        profile_url = telegram_profile_url(getattr(client, "telegram_id", None))
    if profile_url:
        lines.append(f'💬 <a href="{profile_url}">Написать клиенту в Telegram</a>')
    if booking.service_name:
        lines.append(f"✂️ {escape(booking.service_name)} — всего {booking.duration_minutes} мин")
    else:
        lines.append(f"⏱ Длительность: {booking.duration_minutes} мин")
    if booking.comment:
        lines.append(f"📝 Комментарий: {escape(booking.comment)}")
    if booking.master_comment:
        lines.append(f"📌 Заметка мастера: {escape(booking.master_comment)}")
    return "\n".join(lines)


def compact_booking_card_text(booking: Booking, client: Client, index: int | None = None, profile_url: str | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    time_text = booking.time.strftime("%H:%M") if hasattr(booking.time, "strftime") else str(booking.time)[:5]
    lines = [f"{prefix}<b>{time_text}</b> — {escape(client.name)}"]
    if booking.service_name:
        lines.append(f"✂️ {escape(booking.service_name)}")
    lines.append(f"📱 {escape(client.phone or 'Телефон не указан')}")
    if not profile_url:
        profile_url = telegram_profile_url(getattr(client, "telegram_id", None))
    if profile_url:
        lines.append(f'💬 <a href="{profile_url}">Написать</a>')
    return "\n".join(lines)


# Обработчик /start
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if payload.startswith("owner_"):
        from architect.services.account_link_service import account_link_service

        linked = await account_link_service.claim_master_bot_owner(
            payload.removeprefix("owner_"),
            user.id,
            bot.token,
        )
        if linked:
            await message.answer("✅ Telegram-бот привязан. Теперь вы входите в него как мастер.")
        else:
            await message.answer("❌ Ссылка подтверждения владельца недействительна или устарела.")

    master_info, is_admin = await get_master_info(bot.token, user.id)

    if not master_info:
        await message.answer("❌ Бот временно недоступен")
        return

    if not is_admin:
        async with async_session_maker() as session:
            profile = await get_client_profile(session, user.id)
        if not profile:
            await ask_for_contact(message, state)
            return

    await state.clear()
    bot_info = await bot.get_me()
    bot_username = bot_info.username if hasattr(bot_info, "username") else None
    menu = await build_menu(master_info["id"], is_admin, bot.token, user, bot_username, master_info["bot_id"])

    await message.answer(
        f"👋 Добро пожаловать!\n\n{master_info['name']}",
        reply_markup=menu
    )


@router.message(F.contact)
async def handle_registration_contact(message: Message, state: FSMContext, bot: Bot):
    master_info, is_admin = await get_master_info(bot.token, message.from_user.id)
    if not master_info or is_admin:
        return

    contact = message.contact
    if not contact or contact.user_id != message.from_user.id:
        await message.answer(
            "Пожалуйста, используйте кнопку ниже и отправьте именно свой номер телефона.",
            reply_markup=contact_keyboard(),
        )
        return

    try:
        phone = normalize_phone(contact.phone_number)
    except ValueError:
        await message.answer(
            "Telegram передал некорректный номер. Попробуйте ещё раз кнопкой ниже.",
            reply_markup=contact_keyboard(),
        )
        return

    await state.update_data(phone=phone)
    await state.set_state(ClientRegistration.waiting_for_full_name)
    await message.answer(
        "Спасибо, номер получен.\n\n"
        "Теперь напишите фамилию и имя через пробел. Это нужно, чтобы мастер сразу понимал, "
        "для кого создана запись. Например: Иванов Иван.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ClientRegistration.waiting_for_contact)
async def reject_contact_text(message: Message):
    await message.answer(
        "Чтобы исключить ошибку в номере, не вводите телефон текстом. Нажмите кнопку ниже.",
        reply_markup=contact_keyboard(),
    )


@router.message(ClientRegistration.waiting_for_full_name, F.text)
async def handle_registration_full_name(message: Message, state: FSMContext, bot: Bot):
    try:
        full_name = normalize_full_name(message.text)
    except ValueError as error:
        await message.answer(
            f"{error}.\n\nНапишите фамилию и имя через пробел. Например: Иванов Иван."
        )
        return

    data = await state.get_data()
    phone = data.get("phone")
    if not phone:
        await ask_for_contact(message, state)
        return

    master_info, is_admin = await get_master_info(bot.token, message.from_user.id)
    if not master_info or is_admin:
        await state.clear()
        return

    async with async_session_maker() as session:
        profile = await save_client_profile(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            phone=phone,
            name=full_name,
        )
        await ensure_master_client(session, master_info["id"], profile)
        await session.commit()

    await state.clear()
    bot_info = await bot.get_me()
    menu = await build_menu(master_info["id"], False, bot.token, message.from_user, bot_info.username, master_info["bot_id"])
    await message.answer(
        "Готово. Данные сохранены, повторно заполнять их в других ботах мастеров не придётся.\n\n"
        "Теперь можно выбрать действие:",
        reply_markup=menu,
    )


@router.message(ClientRegistration.waiting_for_full_name)
async def reject_non_text_full_name(message: Message):
    await message.answer("Напишите фамилию и имя обычным текстом. Например: Иванов Иван.")


# Обработчик "Мои записи"
@router.callback_query(F.data == "my_bookings")
async def show_my_bookings(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user

    master_info, is_admin = await get_master_info(bot.token, user.id)

    if not is_admin:
        await callback.answer("❌ Нет доступа")
        return

    # Получаем username бота
    bot_info = await bot.get_me()
    bot_username = bot_info.username if hasattr(bot_info, "username") else None

    # Получаем записи на сегодня
    today = date.today()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Booking, Client)
            .join(Client, Booking.client_id == Client.id)
            .where(Booking.master_id == master_info["id"])
            .where(Booking.date == today)
            .where(Booking.status == "upcoming")
            .order_by(Booking.time)
        )
        bookings = result.all()
        profile_urls = {}
        for _, client in bookings:
            if client.telegram_id:
                profile = await get_client_profile(session, client.telegram_id)
                profile_urls[client.id] = telegram_profile_url(
                    client.telegram_id,
                    profile.telegram_username if profile else None,
                )

    today_str = date.today().strftime("%d.%m.%Y")

    if not bookings:
        text = f"📋 Записи на {today_str}:\n\nЗаписей на сегодня нет."
    else:
        text = f"📋 Записи на {today_str}:\n\n"
        text += "\n\n".join(
            compact_booking_card_text(booking, client, i, profile_urls.get(client.id))
            for i, (booking, client) in enumerate(bookings, 1)
        )

    text += "\n👇 Используйте кнопки ниже:"

    menu = await build_menu(master_info["id"], True, bot.token, user, bot_username, master_info["bot_id"])
    await callback.message.edit_text(text, reply_markup=menu)
    await callback.answer()


@router.callback_query(F.data == "bot_url")
async def show_bot_url(callback: CallbackQuery, bot: Bot):
    master_info, is_admin = await get_master_info(bot.token, callback.from_user.id)
    if not master_info or not is_admin:
        await callback.answer("Нет доступа", show_alert=True)
        return

    bot_info = await bot.get_me()
    await callback.message.answer(
        "🔗 Ссылка на вашего бота:\n\n"
        f"https://t.me/{bot_info.username}"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def show_menu_button(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    master_info, is_admin = await get_master_info(bot.token, user.id)
    if not master_info:
        await callback.answer("Бот временно недоступен", show_alert=True)
        return

    # Получаем username бота
    bot_info = await bot.get_me()
    bot_username = bot_info.username if hasattr(bot_info, "username") else None

    parts = callback.data.split(":")
    button_type = parts[1]
    custom_idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    async with async_session_maker() as session:
        result = await session.execute(
            select(MenuButton).where(
                MenuButton.master_id == master_info["id"],
                MenuButton.button_type == button_type,
            )
        )
        button = result.scalar_one_or_none()

    if not button or not is_visible_menu_button_record(button):
        await callback.answer("Кнопка сейчас выключена", show_alert=True)
        return

    menu = await build_menu(master_info["id"], is_admin, bot.token, user, bot_username, master_info["bot_id"])
    content = button.content_json or {}
    text = build_menu_button_text(button_type, content, custom_idx)
    photos = extract_menu_button_photos(button_type, content, custom_idx)
    await send_menu_content(callback.message, text, photos, menu)
    await callback.answer()


@router.callback_query(F.data == "client_help")
async def show_client_help(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    master_info, is_admin = await get_master_info(bot.token, user.id)
    if not master_info:
        await callback.answer("Бот временно недоступен", show_alert=True)
        return
    bot_info = await bot.get_me()
    menu = await build_menu(master_info["id"], is_admin, bot.token, user, bot_info.username, master_info["bot_id"])
    await callback.message.answer(CLIENT_HELP_TEXT, reply_markup=menu)
    await callback.answer()


def build_menu_button_text(button_type: str, content: dict, custom_idx: int | None = None) -> str:
    if button_type == "price":
        items = content.get("items", [])
        lines = [f"{i + 1}. {item.get('name', '')} — {item.get('price', '')}" for i, item in enumerate(items) if item.get("name")]
        return "💰 Прайс-лист:\n\n" + ("\n".join(lines) if lines else "Прайс пока не заполнен")
    if button_type == "faq":
        lines = []
        for i, item in enumerate(content.get("items", [])):
            if item.get("question"):
                lines.append(f"{i + 1}. ❓ {item.get('question')}")
                if item.get("answer"):
                    lines.append(f"   💬 {item.get('answer')}")
        return "❓ Частые вопросы:\n\n" + ("\n".join(lines) if lines else "Вопросы пока не добавлены")
    if button_type == "address":
        return content.get("text") or "📍 Адрес пока не указан"
    if button_type == "portfolio":
        return "🎨 Портфолио" if any(p for p in content.get("photos", []) if p) else "🎨 Портфолио пока не заполнено"
    if button_type == "custom":
        buttons = get_custom_button_items(content)
        item = buttons[custom_idx] if custom_idx is not None and custom_idx < len(buttons) else content
        title = f"{item.get('icon', '')} {item.get('name', 'Информация')}".strip()
        lines = [f"📋 {title}"]
        
        # Support both new list format and old/fallback singular format
        item_texts = item.get("texts", [])
        if not item_texts and item.get("text"):
            item_texts = [item.get("text")]
        lines.extend(t for t in item_texts if t)
        
        item_links = item.get("links", [])
        if not item_links and item.get("url"):
            item_links = [{"text": "Перейти", "url": item.get("url")}]
        
        for link in item_links:
            if link.get("url"):
                l_text = link.get("text") or link.get("url")
                lines.append(f"🔗 {l_text}: {link.get('url')}")
                
        return "\n\n".join(lines)
    return "Информация пока не добавлена"


def is_meaningful_custom_button(item: dict) -> bool:
    name = (item.get("name") or "").strip()
    if not name or name in PLACEHOLDER_CUSTOM_NAMES:
        return False
    return True


def get_custom_button_items(content: dict) -> list[dict]:
    if not isinstance(content, dict):
        return []
    nested = content.get("content")
    if isinstance(nested, dict) and isinstance(nested.get("custom_buttons"), list):
        return nested.get("custom_buttons") or []
    if isinstance(content.get("custom_buttons"), list):
        return content.get("custom_buttons") or []
    return []


def is_visible_menu_button_record(button: MenuButton) -> bool:
    if button.active:
        return True
    if button.button_type != "custom":
        return False
    return any(
        item.get("active") and is_meaningful_custom_button(item)
        for item in get_custom_button_items(button.content_json or {})
    )


def normalize_photo_url(photo_url: str | None) -> str | None:
    photo_url = normalize_media_reference(photo_url)
    if not photo_url:
        return None
    if photo_url.startswith("/"):
        return f"{get_urls()['WEB_URL'].rstrip('/')}{photo_url}"
    return photo_url


async def load_photo(photo_url: str) -> BufferedInputFile:
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        response = await client.get(photo_url)
        response.raise_for_status()

    filename = unquote(PurePosixPath(urlsplit(photo_url).path).name) or "photo.jpg"
    return BufferedInputFile(response.content, filename=filename)


def extract_menu_button_photos(button_type: str, content: dict, custom_idx: int | None = None) -> list[str]:
    if button_type == "address":
        return [content.get("photo")] if content.get("photo") else []
    if button_type == "portfolio":
        return [photo for photo in content.get("photos", []) if photo]
    if button_type == "custom":
        buttons = get_custom_button_items(content)
        item = buttons[custom_idx] if custom_idx is not None and custom_idx < len(buttons) else content
        return [photo for photo in item.get("photos", []) if photo]
    return []


async def send_menu_content(
    message: Message,
    text: str,
    photos: list[str],
    reply_markup: InlineKeyboardMarkup,
) -> None:
    normalized_photos = [url for url in (normalize_photo_url(photo) for photo in photos) if url]
    if not normalized_photos:
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=False)
        return

    await message.answer(text, disable_web_page_preview=False)
    for photo_url in normalized_photos[:10]:
        try:
            await message.answer_photo(photo=await load_photo(photo_url))
        except Exception:
            logger.exception("Failed to send menu photo %s", photo_url)
    await message.answer("Выберите действие:", reply_markup=reply_markup)


# Обработчик "Поделиться"
@router.callback_query(F.data == "share_contact")
async def request_share_contact(callback: CallbackQuery, state: FSMContext, bot: Bot):
    master_info, is_admin = await get_master_info(bot.token, callback.from_user.id)
    if not master_info or not is_admin:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Выбрать контакт", request_user=KeyboardButtonRequestUser(request_id=1))]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await callback.message.answer(
        "📤 Выберите контакт из списка, чтобы отправить ему приглашение:",
        reply_markup=keyboard
    )
    await callback.answer()


# Обработка выбранного контакта
@router.message(F.user_shared)
async def handle_user_shared(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    shared_user_id = message.user_shared.user_id

    master_info, is_admin = await get_master_info(bot.token, user.id)
    if not is_admin:
        return

    # Получаем username бота
    bot_info = await bot.get_me()
    bot_username = bot_info.username if hasattr(bot_info, "username") else None

    try:
        if bot_username:
            invite_text = f"Вы можете записаться ко мне через этого бота: https://t.me/{bot_username}"
        else:
            invite_url = build_url("/call", {"master_id": master_info["id"]})
            invite_text = f"Записаться ко мне можно здесь: {invite_url}"

        await bot.send_message(
            chat_id=shared_user_id,
            text=invite_text
        )

        await message.answer("✅ Сообщение отправлено!", reply_markup=ReplyKeyboardRemove())
        menu = await build_menu(master_info["id"], True, bot.token, user, bot_username, master_info["bot_id"])
        await message.answer("👋 Главное меню:", reply_markup=menu)

    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        await message.answer("❌ Не удалось отправить сообщение", reply_markup=ReplyKeyboardRemove())
