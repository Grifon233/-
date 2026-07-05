from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from architect.keyboards.menu import architect_menu_keyboard, owner_has_bot, owner_has_vk_bot
from architect.services.funnel_events import record_funnel_event
from architect.services.referral_service import referral_service
from architect.services.account_link_service import account_link_service

router = Router()

WELCOME_TEXT = (
    "👋 Добро пожаловать в Архитектор Бот!\n\n"
    "Создайте собственного бота для автоматической записи клиентов "
    "в Telegram и ВКонтакте — без программирования и сложных настроек.\n\n"
    "С помощью бота вы сможете:\n\n"
    "• принимать заявки на запись 24/7 без звонков и переписок;\n"
    "• показывать клиентам только актуальные свободные даты и время;\n"
    "• автоматически отправлять уведомления о новых записях;\n"
    "• хранить расписание и контакты клиентов в одном месте.\n\n"
    "Настройка занимает всего несколько минут. Никаких технических навыков не требуется.\n\n"
    "Начните с демо-версии, чтобы увидеть, как бот работает глазами мастера и клиента."
)


@router.message(Command("start"))
async def cmd_start(message: Message):
    await referral_service.ensure_code(message.from_user.id)
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if payload.startswith("linkvk_"):
        linked = await account_link_service.claim_telegram_link(
            payload.removeprefix("linkvk_"),
            message.from_user.id,
        )
        if linked:
            await message.answer(
                "✅ Аккаунты Telegram и ВКонтакте связаны.\n\n"
                "Теперь в обоих мессенджерах вы будете определяться как владелец и получите доступ "
                "к одной админке, расписанию и подписке."
            )
        else:
            await message.answer(
                "❌ Ссылка привязки недействительна или устарела. Создайте новую ссылку в Архитекторе ВКонтакте."
            )
    utm_source = payload[4:] if payload.startswith("utm_") else None
    metadata = {"utm_source": utm_source} if utm_source else {}
    await record_funnel_event("architect_start", message.from_user.id, metadata=metadata)
    has_bot = await owner_has_bot(message.from_user.id)
    has_vk_bot = await owner_has_vk_bot(message.from_user.id) if has_bot else False
    await message.answer(
        WELCOME_TEXT,
        reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=has_bot, has_vk_bot=has_vk_bot)
    )


# Команда /id - получить свой Telegram ID (доступна всем)
@router.message(Command("id"))
async def cmd_get_id(message: Message):
    await message.answer(
        f"📌 Ваш ID: <code>{message.from_user.id}</code>\n\n"
        "Отправьте этот номер главному мастеру для добавления в аккаунт.",
        parse_mode="HTML"
    )


# Команда /menu - вернуться в меню (доступна всем)
@router.message(Command("menu"))
async def cmd_menu(message: Message):
    has_bot = await owner_has_bot(message.from_user.id)
    has_vk_bot = await owner_has_vk_bot(message.from_user.id) if has_bot else False
    await message.answer(
        "Главное меню:",
        reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=has_bot, has_vk_bot=has_vk_bot)
    )
