"""VK Архитектор — зеркало Telegram-архитектора для VK-сообщества платформы."""
import asyncio
import json
import logging
import re

from sqlalchemy import select

from backend.config import build_url
from backend.tutorial_media import (
    telegram_bot_instruction_video_path,
    vk_bot_instruction_video_path,
)
from backend.database import (
    Booking,
    Client,
    Master,
    MasterBot,
    MasterVkProfile,
    MenuButton,
    Subscription,
    VkBot,
    async_session_maker,
)
from backend.vk import api as vk_api

logger = logging.getLogger(__name__)

_NAV_CMDS = frozenset({
    "about", "demo", "demo_master", "demo_client", "demo_master_bookings", "demo_btn",
    "create_vk_bot", "create_tg_bot", "subscription", "pay_1_month", "pay_6_months",
    "pay_12_months", "enter_promo_code", "link_account", "select_vk_for_tg", "support", "delete_bot",
    "show_vk_instruction_video", "show_tg_instruction_video",
})

_CONFIRM_DELETE_STATES = frozenset({"confirm_delete", "confirm_delete_vk", "confirm_delete_tg"})
_media_tasks: set[asyncio.Task] = set()


def _pseudo_tg_id(vk_id: int) -> int:
    return -vk_id


def _text_btn(label: str, cmd: str) -> list:
    return [{"action": {"type": "text", "label": label[:40], "payload": json.dumps({"cmd": cmd}, ensure_ascii=False)}}]


def _text_btn_payload(label: str, payload: dict) -> list:
    return [{"action": {"type": "text", "label": label[:40], "payload": json.dumps(payload, ensure_ascii=False)}}]


def _link_btn(label: str, url: str) -> list:
    return [{"action": {"type": "open_link", "label": label[:40], "link": url}}]


def _build_keyboard(pseudo_tg_id: int, has_vk_bot: bool, has_tg_bot: bool) -> dict:
    buttons = [
        _text_btn("✨ Как работает бот", "about"),
        _text_btn("👀 Посмотреть демо", "demo"),
        _text_btn("🚀 Создать бота", "create_vk_bot"),
    ]
    if has_vk_bot and not has_tg_bot:
        buttons.append(_text_btn("🔗 Связать с Telegram", "create_tg_bot"))
    buttons += [
        _text_btn("💎 Тарифы и подписка", "subscription"),
        _text_btn("💬 Связаться с поддержкой", "support"),
        _text_btn("🗑 Удалить бота", "delete_bot"),
    ]
    return {"one_time": False, "inline": False, "buttons": buttons}


def _build_demo_keyboard() -> dict:
    return {
        "one_time": False,
        "inline": False,
        "buttons": [
            _text_btn("👨‍💼 Я мастер", "demo_master"),
            _text_btn("👤 Я клиент", "demo_client"),
            _text_btn("◀ Назад", "back"),
        ],
    }


def _build_demo_master_keyboard(pseudo_tg_id: int, vk_id: int, vk_name: str) -> dict:
    demo_calendar_url = build_url("/calendar", {"demo": "1", "user": pseudo_tg_id, "vk_user": vk_id, "name": vk_name})
    return {
        "one_time": False,
        "inline": False,
        "buttons": [
            _link_btn("📅 Открыть календарь", demo_calendar_url),
            _text_btn("📋 Мои записи", "demo_master_bookings"),
            _text_btn("◀ Выйти из демо", "back"),
        ],
    }


async def _get_demo_master_data() -> dict:
    async with async_session_maker() as session:
        result = await session.execute(select(Master).where(Master.is_demo == True))
        master = result.scalar_one_or_none()
    if not master:
        return {}
    return {"id": master.id, "name": master.name}


async def _build_demo_client_keyboard(vk_id: int, vk_name: str) -> dict:
    from backend.handlers.master_bot import (
        get_custom_button_items,
        is_meaningful_custom_button,
        is_visible_menu_button_record,
    )
    demo_booking_url = build_url("/call", {"demo": "1", "vk_user": vk_id, "name": vk_name})
    buttons = [[{"action": {"type": "open_link", "link": demo_booking_url, "label": "📅 Записаться"}}]]

    demo_master = await _get_demo_master_data()
    master_id = demo_master.get("id")
    if master_id:
        async with async_session_maker() as session:
            result = await session.execute(select(MenuButton).where(MenuButton.master_id == master_id))
            menu_buttons = result.scalars().all()
        for btn in menu_buttons:
            if not is_visible_menu_button_record(btn):
                continue
            if btn.button_type == "price":
                buttons.append(_text_btn_payload("💰 Прайс", {"cmd": "demo_btn", "type": "price"}))
            elif btn.button_type == "faq":
                buttons.append(_text_btn_payload("❓ FAQ", {"cmd": "demo_btn", "type": "faq"}))
            elif btn.button_type == "address":
                buttons.append(_text_btn_payload("📍 Адрес", {"cmd": "demo_btn", "type": "address"}))
            elif btn.button_type == "portfolio":
                buttons.append(_text_btn_payload("🎨 Портфолио", {"cmd": "demo_btn", "type": "portfolio"}))
            elif btn.button_type == "custom":
                content = btn.content_json or {}
                for idx, item in enumerate(get_custom_button_items(content)):
                    if item.get("active") and is_meaningful_custom_button(item):
                        label = f"{item.get('icon', '')} {item.get('name', 'Информация')}".strip()
                        buttons.append(_text_btn_payload(label, {"cmd": "demo_btn", "type": "custom", "idx": idx}))
    buttons.append(_text_btn("◀ Выйти из демо", "back"))
    return {"one_time": False, "inline": False, "buttons": buttons[:10]}


async def _demo_bookings_text() -> str:
    """Записи демо-мастера только на сегодня."""
    from datetime import date
    demo_master = await _get_demo_master_data()
    master_id = demo_master.get("id")
    if not master_id:
        return "📋 Записей нет."
    today = date.today()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Booking, Client)
            .outerjoin(Client, Booking.client_id == Client.id)
            .where(Booking.master_id == master_id, Booking.date == today)
            .order_by(Booking.time)
            .limit(20)
        )
        rows = result.all()
    if not rows:
        return f"📋 Записей на сегодня ({today.strftime('%d.%m.%Y')}) нет."
    lines = [f"📋 Записи на сегодня ({today.strftime('%d.%m.%Y')})\n"]
    for b, client in rows:
        time_str = str(b.time)[:5] if b.time else "—"
        client_name = client.name if client else "Гость"
        service = b.service_name or "—"
        lines.append(f"🕐 {time_str} — {client_name} | {service}")
    return "\n".join(lines)


async def _demo_menu_button_response(btn_type: str, custom_idx: int | None) -> tuple[str, list[str]]:
    from backend.handlers.master_bot import (
        build_menu_button_text,
        extract_menu_button_photos,
        is_visible_menu_button_record,
        normalize_photo_url,
    )
    demo_master = await _get_demo_master_data()
    master_id = demo_master.get("id")
    if not master_id:
        return "Информация недоступна.", []
    async with async_session_maker() as session:
        result = await session.execute(
            select(MenuButton).where(
                MenuButton.master_id == master_id,
                MenuButton.button_type == btn_type,
            )
        )
        button = result.scalar_one_or_none()
    if not button or not is_visible_menu_button_record(button):
        return "Эта кнопка сейчас выключена.", []
    content = button.content_json or {}
    text = build_menu_button_text(btn_type, content, custom_idx)
    raw_photos = extract_menu_button_photos(btn_type, content, custom_idx)
    photo_urls = [u for u in (normalize_photo_url(p) for p in raw_photos) if u]
    return text, photo_urls


async def _send_demo_content(vk_token: str, peer_id: int, text: str, photo_urls: list[str], keyboard: dict) -> None:
    await vk_api.send_message(vk_token, peer_id, text, keyboard=keyboard)
    if not photo_urls:
        return

    async def send_photos() -> None:
        attachments, failed_urls = await vk_api.upload_photos_for_message(vk_token, peer_id, photo_urls)
        if attachments:
            await vk_api.send_message(vk_token, peer_id, "📷", attachment=",".join(attachments))
        if failed_urls:
            logger.warning("VK demo: %d photo(s) failed to upload", len(failed_urls))

    task = asyncio.create_task(send_photos())
    _media_tasks.add(task)

    def finish(completed: asyncio.Task) -> None:
        _media_tasks.discard(completed)
        if not completed.cancelled() and completed.exception():
            logger.warning("VK demo media delivery failed: %s", completed.exception())

    task.add_done_callback(finish)


def _build_confirm_delete_keyboard() -> dict:
    return {
        "one_time": True,
        "inline": False,
        "buttons": [
            _text_btn("✅ Да, удалить", "confirm_delete"),
            _text_btn("❌ Отмена", "back"),
        ],
    }


async def _has_vk_community_bot(pseudo_tg_id: int) -> bool:
    from architect.services.vk_bot_manager import vk_bot_manager
    return await vk_bot_manager.get_vk_bot(pseudo_tg_id) is not None


async def _has_tg_bot(pseudo_tg_id: int) -> bool:
    async with async_session_maker() as session:
        vk_master_ids = set((await session.execute(
            select(VkBot.master_id).where(
                VkBot.master_telegram_id == pseudo_tg_id,
                VkBot.status == "running",
            )
        )).scalars().all())
        tg_master_ids = set((await session.execute(
            select(MasterBot.master_id).where(
                MasterBot.master_telegram_id == pseudo_tg_id,
                MasterBot.status == "running",
            )
        )).scalars().all())
    return bool(vk_master_ids) and vk_master_ids.issubset(tg_master_ids)


async def _get_or_create_profile(vk_id: int, vk_token: str) -> MasterVkProfile:
    async with async_session_maker() as session:
        result = await session.execute(select(MasterVkProfile).where(MasterVkProfile.vk_id == vk_id))
        profile = result.scalar_one_or_none()
        if profile:
            return profile

    vk_name = await vk_api.get_user_name(vk_token, vk_id) or "Мастер"
    pseudo_tg = _pseudo_tg_id(vk_id)

    async with async_session_maker() as session:
        master_result = await session.execute(select(Master).where(Master.telegram_id == pseudo_tg))
        master = master_result.scalar_one_or_none()
        if not master:
            master = Master(
                telegram_id=pseudo_tg,
                name=vk_name,
                is_demo=False,
                use_services=False,
                interval_minutes=60,
                schedule_json={},
            )
            session.add(master)
            await session.flush()
        profile = MasterVkProfile(
            vk_id=vk_id,
            pseudo_telegram_id=pseudo_tg,
            master_id=master.id,
            name=vk_name,
            state="main",
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


async def _save_state(vk_id: int, state: str) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(MasterVkProfile).where(MasterVkProfile.vk_id == vk_id))
        profile = result.scalar_one_or_none()
        if profile:
            profile.state = state
            await session.commit()


async def _save_state_data(vk_id: int, **values) -> None:
    async with async_session_maker() as session:
        profile = (await session.execute(
            select(MasterVkProfile).where(MasterVkProfile.vk_id == vk_id)
        )).scalar_one_or_none()
        if profile:
            state_data = dict(profile.state_data_json or {})
            state_data.update(values)
            profile.state_data_json = state_data
            await session.commit()


async def _unlinked_vk_bots(owner_id: int) -> list[dict]:
    async with async_session_maker() as session:
        vk_bots = (await session.execute(
            select(VkBot)
            .where(VkBot.master_telegram_id == owner_id, VkBot.status == "running")
            .order_by(VkBot.created_at, VkBot.id)
        )).scalars().all()
        linked_master_ids = set((await session.execute(
            select(MasterBot.master_id).where(
                MasterBot.master_telegram_id == owner_id,
                MasterBot.status == "running",
            )
        )).scalars().all())
        return [
            {
                "id": bot.id,
                "master_id": bot.master_id,
                "name": bot.group_name or f"VK-бот {bot.id}",
            }
            for bot in vk_bots
            if bot.master_id not in linked_master_ids
        ]


async def _get_subscription_status(pseudo_tg_id: int) -> str:
    from datetime import datetime, timedelta
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.master_telegram_id == pseudo_tg_id, Subscription.status == "active")
            .order_by(Subscription.paid_at.desc())
        )
        sub = result.scalars().first()
    if not sub:
        return "❌ Подписка не активна"
    if sub.lifetime:
        return "✅ Подписка: безлимитная"
    expires = sub.paid_at + timedelta(days=sub.period_days) if sub.paid_at else None
    if expires and expires < datetime.utcnow():
        return "⏰ Подписка истекла"
    return f"✅ Подписка активна до {expires.strftime('%d.%m.%Y') if expires else '—'}"


WELCOME_TEXT = (
    "👋 Добро пожаловать в Архитектор Бот!\n\n"
    "Создайте собственного ВК-бота для автоматической записи клиентов "
    "без программирования и сложных настроек.\n\n"
    "С помощью бота вы сможете:\n\n"
    "• принимать заявки на запись 24/7 без звонков и переписок;\n"
    "• показывать клиентам только актуальные свободные даты и время;\n"
    "• автоматически отправлять уведомления о новых записях;\n"
    "• хранить расписание и контакты клиентов в одном месте.\n\n"
    "Настройка занимает всего несколько минут. Никаких технических навыков не требуется.\n\n"
    "Начните с демо-версии, чтобы увидеть, как бот работает глазами мастера и клиента."
)

ABOUT_TEXT = (
    "✨ Как работает бот\n\n"
    "Вы создаёте своего бота для записи клиентов — без навыков программирования.\n\n"
    "Клиент пишет в ваш бот → видит ваше расписание → выбирает удобное время → "
    "вы получаете уведомление о новой записи.\n\n"
    "Что входит:\n\n"
    "• онлайн-запись через ВКонтакте и Telegram;\n"
    "• настраиваемое расписание с перерывами;\n"
    "• портфолио, прайс, адрес, FAQ;\n"
    "• уведомления вам и клиенту;\n\n"
    "Нажмите «🚀 Создать бота» чтобы начать."
)

SUPPORT_TEXT = (
    "💬 Связаться с поддержкой\n\n"
    "Связь с разработчиками осуществляется через бота в Telegram."
)

VK_BOT_INSTRUCTION = (
    "🔵 Создание бота ВКонтакте:\n\n"
    "1. Откройте ВКонтакте через браузер и создайте сообщество (или используйте существующее).\n"
    "2. В правой панели нажмите «Управление».\n"
    "3. В изменившейся панели справа «Сообщения» → «Настройки для бота» → «Включить возможности ботов» "
    "и отметьте «Добавить кнопку „Начать“».\n"
    "4. После 3 шага в правой панели снова выберите «Дополнительно», затем «Работа с API».\n"
    "5. Вверху выбрано «Ключи доступа» — нажмите «Создать ключ».\n"
    "6. Отметьте все три галочки:\n"
    "   ✅ Разрешить приложению доступ к управлению сообществом\n"
    "   ✅ Разрешить приложению доступ к сообщениям сообщества\n"
    "   ✅ Разрешить приложению доступ к фотографиям сообщества\n"
    "7. Нажмите «Создать», скопируйте ключ:\n"
    "   vk1.a.AbCdEf...\n\n\n"
    "Вставьте ключ в следующее сообщение.\n\n"
    "⚠️ Все три галочки обязательны: без них бот не сможет отправлять фотографии и писать клиентам.\n\n"
    "Напишите «Отмена» чтобы вернуться в меню."
)

TG_BOT_INSTRUCTION = (
    "📱 Привязка Telegram-бота:\n\n"
    "1. Откройте BotFather: https://t.me/BotFather\n"
    "2. Отправьте /newbot\n"
    "3. Придумайте название и имя бота (оканчивается на bot)\n"
    "4. Скопируйте токен:\n"
    "   123456789:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
    "Вставьте токен в следующее сообщение.\n\n"
    "Напишите «Отмена» чтобы вернуться в меню."
)


async def _send_tg_bot_instruction(vk_token: str, peer_id: int, keyboard: dict) -> None:
    await vk_api.send_message(vk_token, peer_id, TG_BOT_INSTRUCTION, keyboard=keyboard)


def _instruction_keyboard(video_cmd: str) -> dict:
    return {
        "one_time": False,
        "inline": False,
        "buttons": [
            _text_btn("Показать видео", video_cmd),
            _text_btn("◀ Отмена", "back"),
        ],
    }


async def _send_instruction_video(
    vk_token: str,
    peer_id: int,
    video_path,
    title: str,
    keyboard: dict,
) -> None:
    sent = await vk_api.send_local_document(
        vk_token,
        peer_id,
        video_path,
        title=title,
        message=title,
        keyboard=keyboard,
    )
    if not sent:
        await vk_api.send_message(
            vk_token,
            peer_id,
            "Видеоинструкция временно недоступна. Попробуйте нажать кнопку ещё раз.",
            keyboard=keyboard,
        )


def _is_valid_tg_token(token: str) -> bool:
    return bool(re.match(r'^\d+:[A-Za-z0-9_-]{30,100}$', token))


async def handle_vk_architect_message(group_id: int, event_object: dict, vk_token: str) -> None:
    message = event_object.get("message") or event_object
    from_id = message.get("from_id")
    peer_id = message.get("peer_id", from_id)
    text = (message.get("text") or "").strip()
    payload_raw = message.get("payload")

    if not from_id or from_id < 0:
        return

    cmd = None
    demo_btn_type = None
    demo_btn_idx = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            cmd = payload.get("cmd")
            demo_btn_type = payload.get("type")
            demo_btn_idx = payload.get("idx")
        except Exception:
            pass

    profile = await _get_or_create_profile(from_id, vk_token)
    from architect.services.account_link_service import account_link_service

    pseudo_tg = account_link_service.owner_id(profile)
    state = profile.state or "main"

    # Отмена / назад
    if text.lower() in ("отмена", "cancel", "/start", "меню") or cmd == "back":
        await _save_state(from_id, "main")
        has_vk = await _has_vk_community_bot(pseudo_tg)
        has_tg = await _has_tg_bot(pseudo_tg)
        await vk_api.send_message(vk_token, peer_id, WELCOME_TEXT,
                                  keyboard=_build_keyboard(pseudo_tg, has_vk, has_tg))
        return

    # Навигационная команда во время ожидания ввода — сбрасываем состояние.
    if cmd in _NAV_CMDS and cmd not in ("show_vk_instruction_video", "show_tg_instruction_video") and state not in ("main",):
        await _save_state(from_id, "main")
        state = "main"

    _cancel_kb = {"one_time": False, "inline": False, "buttons": [_text_btn("◀ Отмена", "back")]}
    if cmd == "show_vk_instruction_video":
        await _send_instruction_video(
            vk_token,
            peer_id,
            vk_bot_instruction_video_path(),
            "Видеоинструкция по созданию бота ВКонтакте",
            _instruction_keyboard("show_vk_instruction_video"),
        )
        return

    if cmd == "show_tg_instruction_video":
        await _send_instruction_video(
            vk_token,
            peer_id,
            telegram_bot_instruction_video_path(),
            "Видеоинструкция по созданию Telegram-бота",
            _instruction_keyboard("show_tg_instruction_video"),
        )
        return

    # --- Ожидание промокода ---
    if state == "waiting_promo_code":
        from architect.services.referral_service import referral_service
        result = await referral_service.apply_code(pseudo_tg, text)
        await _save_state(from_id, "main")
        confirm_kb = {"one_time": False, "inline": False, "buttons": [
            _text_btn("💳 К подписке", "subscription"),
            _text_btn("◀ В меню", "back"),
        ]}
        icon = "✅" if result.ok else "❌"
        await vk_api.send_message(vk_token, peer_id, f"{icon} {result.message}", keyboard=confirm_kb)
        return

    # --- Ожидание ключа VK-сообщества ---
    if state == "waiting_vk_token":
        token_candidate = text.strip()
        if not token_candidate.startswith("vk1."):
            await vk_api.send_message(vk_token, peer_id,
                "❌ Ключ должен начинаться с vk1.\n\n"
                "Скопируйте его из настроек сообщества и отправьте ещё раз, или напишите «Отмена».",
                keyboard=_cancel_kb)
            return
        await vk_api.send_message(vk_token, peer_id, "⏳ Проверяю ключ...")
        try:
            from architect.services.vk_bot_manager import vk_bot_manager
            result = await vk_bot_manager.create_vk_bot(pseudo_tg, token_candidate)
            await _save_state(from_id, "main")
            group_url = f"https://vk.com/club{result['group_id']}"
            has_tg = await _has_tg_bot(pseudo_tg)
            kb = _build_keyboard(pseudo_tg, has_vk_bot=True, has_tg_bot=has_tg)
            await vk_api.send_message(vk_token, peer_id,
                f"✅ Бот успешно создан!\n\n"
                f"Бот: {result['group_name']}\n"
                f"Ссылка для клиентов: {group_url}\n"
                f"Статус: Работает\n\n"
                "Теперь вы можете протестировать своего бота, использовать его для записи, а также "
                "прикрепить бота Telegram. Не забудьте в профиле открыть расписание, указав рабочие "
                "дни и диапазоны часов, иначе другие люди не будут видеть окна для записи.\n"
                f"Откройте {group_url} и нажмите «Начать», чтобы бот мог присылать вам уведомления о записях.\n"
                "Пожалуйста, оплатите подписку в течение 2 часов, иначе бот будет удалён.",
                keyboard=kb)
        except ValueError as e:
            await vk_api.send_message(vk_token, peer_id,
                f"❌ {e}\n\nИсправьте и отправьте ключ снова, или напишите «Отмена».",
                keyboard=_cancel_kb)
        except Exception:
            logger.exception("VK Architect: create_vk_bot failed for vk_id=%s", from_id)
            await vk_api.send_message(vk_token, peer_id,
                "❌ Не удалось создать бота. Попробуйте позже или напишите «Отмена».",
                keyboard=_cancel_kb)
        return

    # --- Ожидание Telegram-токена ---
    if state == "waiting_tg_token":
        token_candidate = text.strip()
        if not _is_valid_tg_token(token_candidate):
            await vk_api.send_message(vk_token, peer_id,
                "❌ Не похоже на токен бота. Он выглядит так:\n"
                "123456789:ABCdefGHIjklMNOpqrsTUVwxyz\n\n"
                "Попробуйте ещё раз или напишите «Отмена».",
                keyboard=_cancel_kb)
            return
        await vk_api.send_message(vk_token, peer_id, "⏳ Проверяю токен...")
        try:
            from architect.services.bot_manager import bot_manager
            selected_master_id = (profile.state_data_json or {}).get("selected_vk_master_id")
            result = await bot_manager.create_bot(
                pseudo_tg,
                token_candidate,
                profile.name,
                profile_master_id=int(selected_master_id) if selected_master_id else None,
            )
            from architect.services.account_link_service import account_link_service

            username = str(result["username"]).lstrip("@")
            owner_link = await account_link_service.create_master_bot_owner_link(
                from_id,
                result["bot_id"],
                username,
            )
            await _save_state(from_id, "main")
            await _save_state_data(from_id, selected_vk_master_id=None)
            all_linked = not await _unlinked_vk_bots(pseudo_tg)
            confirm_kb = {
                "one_time": False,
                "inline": False,
                "buttons": [
                    _link_btn("Открыть Telegram-бота как мастер", owner_link),
                    *_build_keyboard(pseudo_tg, True, all_linked)["buttons"],
                ][:10],
            }
            await vk_api.send_message(vk_token, peer_id,
                f"✅ Telegram-бот @{username} привязан!\n\n"
                "Откройте его кнопкой ниже и нажмите «Старт», чтобы подтвердить владельца. "
                "После подтверждения вам откроется панель мастера, а клиентам — меню записи.",
                keyboard=confirm_kb)
        except ValueError as e:
            await vk_api.send_message(vk_token, peer_id,
                f"❌ {e}\n\nПроверьте токен и отправьте ещё раз.", keyboard=_cancel_kb)
        except Exception:
            logger.exception("VK Architect: create_bot failed for vk_id=%s", from_id)
            await vk_api.send_message(vk_token, peer_id,
                "❌ Не удалось привязать бота. Попробуйте позже или напишите «Отмена».", keyboard=_cancel_kb)
        return

    # --- Подтверждение удаления ---
    if state in _CONFIRM_DELETE_STATES:
        if cmd == "confirm_delete":
            try:
                if state in ("confirm_delete", "confirm_delete_vk"):
                    from architect.services.vk_bot_manager import vk_bot_manager
                    await vk_bot_manager.delete_vk_bot(pseudo_tg)
                    deleted_label = "VK-бот удалён"
                else:
                    from architect.services.bot_manager import bot_manager
                    await bot_manager.delete_bot(pseudo_tg)
                    deleted_label = "Telegram-бот удалён"
            except Exception:
                logger.exception("VK Architect: delete failed for vk_id=%s state=%s", from_id, state)
                deleted_label = "Бот удалён"
            await _save_state(from_id, "main")
            has_vk = await _has_vk_community_bot(pseudo_tg)
            has_tg = await _has_tg_bot(pseudo_tg)
            kb = _build_keyboard(pseudo_tg, has_vk, has_tg)
            await vk_api.send_message(vk_token, peer_id,
                f"🗑 {deleted_label}. Вы можете создать нового в любое время.", keyboard=kb)
        else:
            await _save_state(from_id, "main")
            has_vk = await _has_vk_community_bot(pseudo_tg)
            has_tg = await _has_tg_bot(pseudo_tg)
            await vk_api.send_message(vk_token, peer_id, "Отмена удаления.",
                                      keyboard=_build_keyboard(pseudo_tg, has_vk, has_tg))
        return

    # --- Команды главного меню ---
    has_vk = await _has_vk_community_bot(pseudo_tg)
    has_tg = await _has_tg_bot(pseudo_tg)
    kb = _build_keyboard(pseudo_tg, has_vk, has_tg)

    if cmd == "about":
        await vk_api.send_message(vk_token, peer_id, ABOUT_TEXT, keyboard=kb)
        return

    if cmd == "demo":
        await vk_api.send_message(vk_token, peer_id,
            "👁 Посмотреть демо\n\nВыберите, от чьего лица хотите посмотреть:",
            keyboard=_build_demo_keyboard())
        return

    if cmd == "demo_master":
        demo_master_kb = _build_demo_master_keyboard(pseudo_tg, from_id, profile.name)
        await vk_api.send_message(vk_token, peer_id,
            "👨‍💼 Демо — Режим мастера\n\n"
            "Нажмите «Открыть календарь», чтобы посмотреть панель мастера и готовые настройки.\n"
            "Редактирование в демо выключено — данные доступны только для просмотра.",
            keyboard=demo_master_kb)
        return

    if cmd == "demo_master_bookings":
        text_content = await _demo_bookings_text()
        demo_master_kb = _build_demo_master_keyboard(pseudo_tg, from_id, profile.name)
        await vk_api.send_message(vk_token, peer_id, text_content, keyboard=demo_master_kb)
        return

    if cmd == "demo_client":
        demo_master = await _get_demo_master_data()
        master_name = demo_master.get("name", "Мастер")
        demo_client_kb = await _build_demo_client_keyboard(from_id, profile.name)
        await vk_api.send_message(vk_token, peer_id,
            f"👤 {master_name}\n\nДобро пожаловать! Выберите действие:",
            keyboard=demo_client_kb)
        return

    if cmd == "demo_btn":
        resp_text, resp_photos = await _demo_menu_button_response(demo_btn_type or "", demo_btn_idx)
        demo_client_kb = await _build_demo_client_keyboard(from_id, profile.name)
        await _send_demo_content(vk_token, peer_id, resp_text, resp_photos, demo_client_kb)
        return

    if cmd == "create_vk_bot":
        await _save_state(from_id, "waiting_vk_token")
        await vk_api.send_message(
            vk_token,
            peer_id,
            VK_BOT_INSTRUCTION,
            keyboard=_instruction_keyboard("show_vk_instruction_video"),
        )
        return

    if cmd == "create_tg_bot":
        available = await _unlinked_vk_bots(pseudo_tg)
        if not available:
            await vk_api.send_message(vk_token, peer_id,
                "Нет VK-ботов, которым требуется Telegram-бот. Сначала создайте новый VK-бот.",
                keyboard=kb)
            return
        if len(available) > 1:
            select_kb = {
                "one_time": False,
                "inline": False,
                "buttons": [
                    _text_btn_payload(item["name"], {"cmd": "select_vk_for_tg", "master_id": item["master_id"]})
                    for item in available[:9]
                ] + [_text_btn("◀ Назад", "back")],
            }
            await vk_api.send_message(
                vk_token,
                peer_id,
                "Выберите VK-бота, к которому нужно подключить Telegram:",
                keyboard=select_kb,
            )
            return
        await _save_state_data(from_id, selected_vk_master_id=available[0]["master_id"])
        await _save_state(from_id, "waiting_tg_token")
        await _send_tg_bot_instruction(vk_token, peer_id, _instruction_keyboard("show_tg_instruction_video"))
        return

    if cmd == "select_vk_for_tg":
        selected_master_id = payload.get("master_id") if payload_raw else None
        available = await _unlinked_vk_bots(pseudo_tg)
        if not selected_master_id or int(selected_master_id) not in {item["master_id"] for item in available}:
            await vk_api.send_message(vk_token, peer_id, "Этот VK-бот уже связан или недоступен.", keyboard=kb)
            return
        await _save_state_data(from_id, selected_vk_master_id=int(selected_master_id))
        await _save_state(from_id, "waiting_tg_token")
        await _send_tg_bot_instruction(vk_token, peer_id, _instruction_keyboard("show_tg_instruction_video"))
        return

    if cmd == "link_account":
        from architect.services.account_link_service import account_link_service

        link = await account_link_service.create_telegram_link(from_id)
        link_kb = {
            "one_time": False,
            "inline": False,
            "buttons": [
                _link_btn("Открыть Архитектор в Telegram", link),
                _text_btn("◀ Назад", "back"),
            ],
        }
        await vk_api.send_message(
            vk_token,
            peer_id,
            "🔗 Связь аккаунтов\n\n"
            "Откройте ссылку в Telegram и нажмите «Старт». Ссылка действует 15 минут и может быть "
            "использована только один раз.",
            keyboard=link_kb,
        )
        return

    if cmd == "subscription":
        from architect.services.referral_service import referral_service
        status_text = await _get_subscription_status(pseudo_tg)
        try:
            ref_code = await referral_service.ensure_code(pseudo_tg)
            can_use_promo = not await referral_service.has_paid_before(pseudo_tg)
            applied_code = await referral_service.get_applied_code(pseudo_tg)
        except Exception:
            ref_code = None
            can_use_promo = False
            applied_code = None
        promo_line = f"Ваш промокод: {ref_code}" if ref_code else ""
        if applied_code:
            promo_line = f"Применён промокод: {applied_code}\n{promo_line}"
        sub_text = (
            f"💎 Тарифы и подписка\n\n"
            f"{status_text}\n\n"
            "Выберите период подписки. После выбора откроется официальная страница YooKassa.\n\n"
            f"{promo_line}\n\n"
            "Поделитесь промокодом с другом — после его первой оплаты вы оба получите по одному "
            "подарочному месяцу подписки."
        ) if promo_line else (
            f"💎 Тарифы и подписка\n\n"
            f"{status_text}\n\n"
            "Выберите период подписки. После выбора откроется официальная страница YooKassa."
        )
        sub_buttons = [
            _text_btn("🥉 1 месяц — 450 ₽", "pay_1_month"),
            _text_btn("🥇 6 месяцев — 2 700 ₽", "pay_6_months"),
            _text_btn("👑 12 месяцев — 5 300 ₽", "pay_12_months"),
        ]
        if can_use_promo:
            sub_buttons.append(_text_btn("🎁 Ввести промокод", "enter_promo_code"))
        sub_buttons.append(_text_btn("◀ Назад", "back"))
        sub_kb = {"one_time": False, "inline": False, "buttons": sub_buttons}
        await vk_api.send_message(vk_token, peer_id, sub_text, keyboard=sub_kb)
        return

    if cmd == "enter_promo_code":
        from architect.services.referral_service import referral_service
        if await referral_service.has_paid_before(pseudo_tg):
            await vk_api.send_message(vk_token, peer_id,
                "❌ Промокод можно применить только до первой оплаты.", keyboard=kb)
            return
        await _save_state(from_id, "waiting_promo_code")
        cancel_kb = {"one_time": False, "inline": False, "buttons": [_text_btn("◀ Отмена", "back")]}
        await vk_api.send_message(vk_token, peer_id,
            "🎁 Введите промокод для получения бесплатного месяца подписки после первой оплаты.",
            keyboard=cancel_kb)
        return

    if cmd in {"pay_1_month", "pay_6_months", "pay_12_months"}:
        period = cmd.removeprefix("pay_")
        try:
            from architect.services.yookassa_payment import yookassa_payment

            payment = await yookassa_payment.create_payment_link(pseudo_tg, period)
            payment_kb = {
                "one_time": False,
                "inline": False,
                "buttons": [
                    _link_btn("💰 Перейти к оплате", payment["url"]),
                    _text_btn("◀ Назад к тарифам", "subscription"),
                ],
            }
            await vk_api.send_message(
                vk_token,
                peer_id,
                f"💳 Оформление подписки на {payment['period_label']}\n\n"
                f"Сумма: {payment['amount']:.0f} ₽\n\n"
                "Нажмите кнопку ниже. Откроется защищённая страница YooKassa, "
                "где доступны все способы оплаты.",
                keyboard=payment_kb,
            )
        except ValueError as error:
            logger.warning("VK payment is not configured for %s: %s", from_id, error)
            await vk_api.send_message(
                vk_token,
                peer_id,
                "❌ Сейчас не удалось подготовить оплату. Попробуйте немного позже.",
                keyboard=kb,
            )
        except Exception:
            logger.exception("VK Architect: payment creation failed for vk_id=%s", from_id)
            await vk_api.send_message(
                vk_token,
                peer_id,
                "❌ Не удалось открыть оплату. Попробуйте немного позже.",
                keyboard=kb,
            )
        return

    if cmd == "support":
        support_kb = {"one_time": False, "inline": False, "buttons": [
            _link_btn("💬 Перейти в бота в Телеграм для связи с разработчиками", "https://t.me/SoftwareArchitects_bot"),
            _text_btn("◀ Назад", "back"),
        ]}
        await vk_api.send_message(vk_token, peer_id, SUPPORT_TEXT, keyboard=support_kb)
        return

    if cmd == "delete_bot":
        if has_vk:
            await _save_state(from_id, "confirm_delete_vk")
            await vk_api.send_message(vk_token, peer_id,
                "🗑 Удаление VK-бота\n\nВы уверены? Бот будет отключён и удалён из системы. "
                "Настройки, расписание и клиенты останутся — можно будет создать бота заново.",
                keyboard=_build_confirm_delete_keyboard())
        elif has_tg:
            await _save_state(from_id, "confirm_delete_tg")
            await vk_api.send_message(vk_token, peer_id,
                "🗑 Удаление Telegram-бота\n\nВы уверены? Бот будет отключён и удалён из системы. "
                "Настройки, расписание и клиенты останутся — можно будет создать бота заново.",
                keyboard=_build_confirm_delete_keyboard())
        else:
            await vk_api.send_message(vk_token, peer_id,
                "У вас нет созданного бота.", keyboard=kb)
        return

    await vk_api.send_message(vk_token, peer_id, WELCOME_TEXT, keyboard=kb)
