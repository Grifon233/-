"""Логика сообщество-бота ВКонтакте мастера: меню записи и ответы на кнопки.

Зеркало backend/handlers/master_bot.py, но для VK. VK-бот — только клиентский:
мастер управляет настройками через Telegram-архитектор и веб-календарь.
"""
import asyncio
import json
import logging
import time
from datetime import date

from sqlalchemy import delete, select

from backend.config import build_url, get_urls
from backend.database import (
    async_session_maker,
    Booking,
    Client,
    Master,
    MenuButton,
    VkBot,
    VkClientProfile,
    VkClientRegistration,
)
from backend.client_profiles import normalize_phone, normalize_full_name
from backend.handlers.master_bot import (
    build_menu_button_text,
    extract_menu_button_photos,
    get_custom_button_items,
    is_meaningful_custom_button,
    is_visible_menu_button_record,
    normalize_photo_url,
)
from backend.middleware.tg_auth import sign_auth_params
from backend.token_utils import decrypt_token
from backend.vk import api
from backend.vk.auth import sign_vk_client_access

logger = logging.getLogger(__name__)
VK_ARCHITECT_BOT_URL = "https://vk.com/club239516667"

VK_CLIENT_HELP_TEXT = (
    "ℹ️ Как использовать бота\n\n"
    "1. Чтобы записаться, нажмите кнопку «Записаться» и перейдите на сайт. В календаре выберите дату, "
    "затем свободное время, при необходимости оставьте комментарий и нажмите «Записаться». "
    "После этого мастер получит уведомление о вашей записи.\n\n"
    "2. Авторизация на сайте происходит автоматически через ваш аккаунт ВКонтакте. "
    "К записи прикрепляются имя и телефон, которые вы указали при первом входе в бота.\n\n"
    "3. Если дата в календаре неактивна — запись на неё ещё не открыта или день недоступен.\n\n"
    "4. По умолчанию запись создаётся на ваши данные. Чтобы записать другого человека, "
    "укажите его имя и телефон в комментарии."
)

_media_tasks: set[asyncio.Task] = set()


def _finish_media_task(task: asyncio.Task) -> None:
    _media_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error:
        logger.warning("VK media delivery failed: %s", error)


async def get_vk_master(group_id: int) -> tuple[dict, str] | None:
    """По group_id возвращает ({master...}, raw_token) активного VK-бота."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(VkBot).where(VkBot.group_id == group_id, VkBot.status == "running")
        )
        vk_bot = result.scalars().first()
        if not vk_bot:
            return None
        master = await session.get(Master, vk_bot.master_id) if vk_bot.master_id else None
        if not master:
            result = await session.execute(select(Master).where(Master.telegram_id == vk_bot.master_telegram_id))
            master = result.scalar_one_or_none()
        if not master:
            return None
        return (
            {
                "id": master.id,
                "name": master.name,
                "bot_id": vk_bot.id,
                "group_id": group_id,
                "master_telegram_id": vk_bot.master_telegram_id,
                "owner_vk_id": vk_bot.owner_vk_id,
            },
            decrypt_token(vk_bot.token),
        )


async def _get_registration(group_id: int, vk_id: int) -> VkClientRegistration | None:
    async with async_session_maker() as session:
        return (await session.execute(
            select(VkClientRegistration).where(
                VkClientRegistration.group_id == group_id,
                VkClientRegistration.vk_id == vk_id,
            )
        )).scalar_one_or_none()


async def _start_registration(group_id: int, vk_id: int) -> None:
    async with async_session_maker() as session:
        existing = (await session.execute(
            select(VkClientRegistration).where(
                VkClientRegistration.group_id == group_id,
                VkClientRegistration.vk_id == vk_id,
            )
        )).scalar_one_or_none()
        if not existing:
            session.add(VkClientRegistration(group_id=group_id, vk_id=vk_id, step="phone"))
        await session.commit()


async def _save_registration_phone(group_id: int, vk_id: int, phone: str) -> None:
    async with async_session_maker() as session:
        state = (await session.execute(
            select(VkClientRegistration).where(
                VkClientRegistration.group_id == group_id,
                VkClientRegistration.vk_id == vk_id,
            )
        )).scalar_one()
        state.phone = phone
        state.step = "name"
        await session.commit()


async def _finish_registration(group_id: int, vk_id: int) -> None:
    async with async_session_maker() as session:
        await session.execute(
            delete(VkClientRegistration).where(
                VkClientRegistration.group_id == group_id,
                VkClientRegistration.vk_id == vk_id,
            )
        )
        await session.commit()


async def _get_vk_profile(vk_id: int) -> VkClientProfile | None:
    async with async_session_maker() as session:
        result = await session.execute(select(VkClientProfile).where(VkClientProfile.vk_id == vk_id))
        return result.scalar_one_or_none()


async def _save_vk_profile_and_client(vk_id: int, master_id: int, phone: str, name: str) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(VkClientProfile).where(VkClientProfile.vk_id == vk_id))
        profile = result.scalar_one_or_none()
        if profile:
            profile.phone = phone
            profile.name = name
        else:
            profile = VkClientProfile(vk_id=vk_id, phone=phone, name=name)
            session.add(profile)

        # Карточка клиента у конкретного мастера.
        result = await session.execute(
            select(Client).where(Client.master_id == master_id, Client.vk_id == vk_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.name = name
            client.phone = phone
        else:
            # Привязка к ранее заведённой мастером карточке по телефону.
            result = await session.execute(
                select(Client).where(
                    Client.master_id == master_id,
                    Client.vk_id.is_(None),
                    Client.telegram_id.is_(None),
                    Client.phone == phone,
                )
            )
            client = result.scalar_one_or_none()
            if client:
                client.vk_id = vk_id
                client.name = name
                client.phone = phone
            else:
                session.add(Client(master_id=master_id, vk_id=vk_id, name=name, phone=phone))
        await session.commit()


def _booking_url(master_id: int, vk_bot_id: int, vk_id: int, name: str | None, token: str) -> str:
    auth_ts = int(time.time())
    params = {
        "master_id": master_id,
        "vk_bot_id": vk_bot_id,
        "vk_user": vk_id,
        "auth_ts": auth_ts,
        "vk_sig": sign_vk_client_access(vk_id, master_id, token, auth_ts),
    }
    if name:
        params["name"] = name
    return build_url("/call", params)


def _master_calendar_url(
    master_id: int,
    owner_id: int,
    owner_vk_id: int | None,
    name: str | None,
) -> str:
    auth_ts = int(time.time())
    signature = sign_auth_params(owner_id, auth_ts)
    params = {
        "master_id": master_id,
        "user": owner_id,
        "auth_ts": auth_ts,
        "auth_source": "vk",
    }
    if signature:
        params["sig"] = signature
    if name:
        params["name"] = name
    if owner_vk_id:
        params["vk_user"] = owner_vk_id
    return build_url("/calendar", params)


def build_vk_master_menu(master: dict, owner_name: str | None = None) -> dict:
    return {
        "one_time": False,
        "inline": False,
        "buttons": [
            [{
                "action": {
                    "type": "open_link",
                    "link": _master_calendar_url(
                        master["id"],
                        master["master_telegram_id"],
                        master.get("owner_vk_id"),
                        owner_name,
                    ),
                    "label": "📅 Календарь",
                }
            }],
            [{
                "action": {
                    "type": "text",
                    "label": "📋 Мои записи",
                    "payload": json.dumps({"cmd": "master_bookings"}, ensure_ascii=False),
                }
            }],
            [{
                "action": {
                    "type": "text",
                    "label": "📤 Поделиться ссылкой на бота",
                    "payload": json.dumps({"cmd": "master_share"}, ensure_ascii=False),
                }
            }],
            [{
                "action": {
                    "type": "text",
                    "label": "🔗 Создать URL-ссылку на бота",
                    "payload": json.dumps({"cmd": "master_url"}, ensure_ascii=False),
                }
            }],
        ],
    }


async def _master_bookings_text(master_id: int) -> str:
    async with async_session_maker() as session:
        rows = (await session.execute(
            select(Booking, Client)
            .join(Client, Booking.client_id == Client.id)
            .where(
                Booking.master_id == master_id,
                Booking.date == date.today(),
                Booking.status.in_(["upcoming", "confirmed"]),
            )
            .order_by(Booking.time)
            .limit(30)
        )).all()
    if not rows:
        return "📋 На сегодня записей нет."
    lines = ["📋 Записи на сегодня:\n"]
    for booking, client in rows:
        time_text = booking.time.strftime("%H:%M") if hasattr(booking.time, "strftime") else str(booking.time)[:5]
        service = f" — {booking.service_name}" if booking.service_name else ""
        phone = f"\n📱 {client.phone}" if client.phone else ""
        profile = f"\n💬 https://vk.com/id{client.vk_id}" if client.vk_id else ""
        lines.append(f"🕐 {time_text} — {client.name}{service}{phone}{profile}")
    return "\n\n".join(lines)


async def build_vk_menu(
    master_id: int,
    vk_id: int,
    name: str | None,
    token: str,
    group_id: int = 0,
    vk_bot_id: int = 0,
) -> dict:
    """Строит VK-клавиатуру: Записаться + активные кнопки меню + помощь."""
    # Имя для отображения в мини-аппе берём из настоящего профиля ВКонтакте,
    # а не из того, что клиент когда-то ввёл при регистрации (мог быть мусор вроде «ААА»).
    display_name = await api.get_user_name(token, vk_id) or name
    booking_button = [{
        "action": {
            "type": "open_link",
            "link": _booking_url(master_id, vk_bot_id, vk_id, display_name, token),
            "label": "📅 Записаться",
        }
    }]
    content_buttons = []

    async with async_session_maker() as session:
        result = await session.execute(select(MenuButton).where(MenuButton.master_id == master_id))
        menu_buttons = result.scalars().all()

    def text_btn(label: str, payload: dict) -> list:
        return [{"action": {"type": "text", "label": label[:40], "payload": json.dumps(payload, ensure_ascii=False)}}]

    for btn in menu_buttons:
        if not is_visible_menu_button_record(btn):
            continue
        if btn.button_type == "price":
            content_buttons.append(text_btn("💰 Прайс", {"cmd": "price"}))
        elif btn.button_type == "faq":
            content_buttons.append(text_btn("❓ FAQ", {"cmd": "faq"}))
        elif btn.button_type == "address":
            content_buttons.append(text_btn("📍 Адрес", {"cmd": "address"}))
        elif btn.button_type == "portfolio":
            content_buttons.append(text_btn("🎨 Портфолио", {"cmd": "portfolio"}))
        elif btn.button_type == "custom":
            content = btn.content_json or {}
            for idx, item in enumerate(get_custom_button_items(content)):
                if item.get("active") and is_meaningful_custom_button(item):
                    label = f"{item.get('icon', '')} {item.get('name', 'Информация')}".strip()
                    content_buttons.append(text_btn(label, {"cmd": "custom", "idx": idx}))

    trailing_buttons = [text_btn("ℹ️ Как пользоваться", {"cmd": "help"})]
    trailing_buttons.append([{
        "action": {"type": "open_link", "link": VK_ARCHITECT_BOT_URL, "label": "🤖 Хочу себе такого же бота"}
    }])

    # VK допускает не более 10 рядов. Всегда сохраняем запись и служебные
    # кнопки, сокращая только пользовательский контент.
    content_limit = max(0, 10 - 1 - len(trailing_buttons))
    buttons = [booking_button, *content_buttons[:content_limit], *trailing_buttons]
    return {"one_time": False, "inline": False, "buttons": buttons}


async def _menu_button_response(master_id: int, button_type: str, custom_idx: int | None) -> tuple[str, list[str]]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(MenuButton).where(MenuButton.master_id == master_id, MenuButton.button_type == button_type)
        )
        button = result.scalar_one_or_none()
    if not button or not is_visible_menu_button_record(button):
        return "Эта кнопка сейчас выключена.", []
    content = button.content_json or {}
    text = build_menu_button_text(button_type, content, custom_idx)
    photos = extract_menu_button_photos(button_type, content, custom_idx)
    photo_urls = [u for u in (normalize_photo_url(p) for p in photos) if u]
    return text, photo_urls


async def _send_vk_photo_batch(token: str, peer_id: int, photo_urls: list[str]) -> None:
    """Upload photos efficiently and send one compact portfolio message."""
    urls = list(dict.fromkeys(url for url in photo_urls if url))[:10]
    if not urls:
        return
    started_at = time.monotonic()
    attachments, failed = await api.upload_photos_for_message(token, peer_id, urls)
    if attachments:
        await api.send_message(token, peer_id, "📷", attachment=",".join(attachments))
    elapsed = time.monotonic() - started_at
    logger.info(
        "VK media delivery: %d/%d photo(s) in %.2fs",
        len(attachments),
        len(urls),
        elapsed,
    )
    if failed:
        logger.warning("VK: %d photo(s) failed to upload", len(failed))


async def _send_vk_content(token: str, peer_id: int, text: str, photo_urls: list[str], keyboard: dict | None) -> None:
    """Отправляет текст сразу, а фотографии догружает в фоне."""
    await api.send_message(token, peer_id, text, keyboard=keyboard)
    if not photo_urls:
        return
    task = asyncio.create_task(_send_vk_photo_batch(token, peer_id, photo_urls))
    _media_tasks.add(task)
    task.add_done_callback(_finish_media_task)


async def handle_vk_message(group_id: int, event_object: dict) -> None:
    """Обрабатывает событие message_new от Long Poll."""
    message = event_object.get("message") or event_object
    from_id = message.get("from_id")
    peer_id = message.get("peer_id", from_id)
    text = (message.get("text") or "").strip()
    payload_raw = message.get("payload")

    if not from_id or from_id < 0:
        return  # игнорируем сообщения от сообществ/ботов

    master_token = await get_vk_master(group_id)
    if not master_token:
        return
    master, token = master_token

    if master.get("owner_vk_id") and from_id == master["owner_vk_id"]:
        cmd = None
        if payload_raw:
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
                cmd = payload.get("cmd")
            except (json.JSONDecodeError, AttributeError):
                pass
        keyboard = build_vk_master_menu(master, master["name"])
        if cmd == "master_bookings":
            await api.send_message(
                token,
                peer_id,
                await _master_bookings_text(master["id"]),
                keyboard=keyboard,
            )
        elif cmd in {"master_share", "master_url"}:
            group_url = f"https://vk.com/club{master['group_id']}"
            prefix = (
                "Отправьте эту ссылку клиенту, чтобы он мог записаться к вам:"
                if cmd == "master_share"
                else "URL-ссылка на вашего бота:"
            )
            await api.send_message(token, peer_id, f"{prefix}\n\n{group_url}", keyboard=keyboard)
        else:
            await api.send_message(
                token,
                peer_id,
                f"👋 {master['name']}\nПанель мастера:",
                keyboard=keyboard,
            )
        return

    profile = await _get_vk_profile(from_id)

    # --- Регистрация нового клиента ---
    if not profile:
        state = await _get_registration(group_id, from_id)
        if not state:
            await _start_registration(group_id, from_id)
            await api.send_message(
                token, peer_id,
                "Здравствуйте! Чтобы записаться, оставьте номер телефона для связи.\n\n"
                "Напишите его в ответном сообщении, например: +7 900 123-45-67",
            )
            return
        if state.step == "phone":
            try:
                phone = normalize_phone(text)
            except ValueError:
                await api.send_message(token, peer_id, "Не получилось распознать номер. Напишите его цифрами, например: +7 900 123-45-67")
                return
            await _save_registration_phone(group_id, from_id, phone)
            await api.send_message(token, peer_id, "Спасибо! Теперь напишите фамилию и имя через пробел. Например: Иванов Иван.")
            return
        if state.step == "name":
            try:
                full_name = normalize_full_name(text)
            except ValueError as e:
                await api.send_message(token, peer_id, f"{e}.\n\nНапишите фамилию и имя через пробел. Например: Иванов Иван.")
                return
            phone = state.phone
            await _save_vk_profile_and_client(from_id, master["id"], phone, full_name)
            await _finish_registration(group_id, from_id)
            keyboard = await build_vk_menu(
                master["id"], from_id, full_name, token,
                group_id=master["group_id"], vk_bot_id=master["bot_id"],
            )
            await api.send_message(
                token, peer_id,
                f"Готово, данные сохранены!\n\n👋 {master['name']}\nВыберите действие:",
                keyboard=keyboard,
            )
            return

    # --- Клиент зарегистрирован: обрабатываем кнопки ---
    cmd = None
    custom_idx = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            cmd = payload.get("cmd")
            custom_idx = payload.get("idx")
        except (json.JSONDecodeError, AttributeError):
            cmd = None

    if cmd in ("price", "faq", "address", "portfolio", "custom"):
        resp_text, resp_photos = await _menu_button_response(master["id"], cmd, custom_idx)
        keyboard = await build_vk_menu(
            master["id"], from_id, profile.name, token,
            group_id=master["group_id"], vk_bot_id=master["bot_id"],
        )
        await _send_vk_content(token, peer_id, resp_text, resp_photos, keyboard)
        return
    if cmd == "help":
        keyboard = await build_vk_menu(
            master["id"], from_id, profile.name, token,
            group_id=master["group_id"], vk_bot_id=master["bot_id"],
        )
        await api.send_message(token, peer_id, VK_CLIENT_HELP_TEXT, keyboard=keyboard)
        return

    # Любое другое сообщение — показываем главное меню.
    keyboard = await build_vk_menu(
        master["id"], from_id, profile.name, token,
        group_id=master["group_id"], vk_bot_id=master["bot_id"],
    )
    await api.send_message(token, peer_id, f"👋 {master['name']}\nВыберите действие:", keyboard=keyboard)
