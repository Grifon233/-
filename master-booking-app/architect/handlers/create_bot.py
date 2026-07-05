import re
import logging
from aiogram import Router, F
from aiogram.types import FSInputFile, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from architect.keyboards.menu import architect_menu_keyboard, main_menu_keyboard, owner_has_bot, owner_has_vk_bot
from architect.handlers.start import WELCOME_TEXT
from architect.services.bot_manager import bot_manager
from backend.tutorial_media import (
    get_instruction_file_id,
    save_instruction_file_id,
    telegram_bot_instruction_video_path,
)

logger = logging.getLogger(__name__)

router = Router()

BOT_STATUS_LABELS = {
    "running": "Работает",
    "creating": "Создаётся",
    "error": "Ошибка",
    "frozen": "Заморожен",
    "stopped": "Остановлен",
}


class CreateBotStates(StatesGroup):
    waiting_for_token = State()


def is_valid_telegram_token(token: str) -> bool:
    pattern = r'^\d+:[A-Za-z0-9_-]{30,100}$'
    return bool(re.match(pattern, token))


CREATE_BOT_INSTRUCTION_TEXT = (
    "📱 Создание нового бота:\n\n"
    "1. Откройте @BotFather в Telegram\n"
    "2. Отправьте команду /newbot\n"
    "3. Придумайте имя вашего бота. Название должно заканчиваться на bot, например zapis1133bot. На этом этапе, если у вас не получилось его создать, попробуйте другое имя: иногда @BotFather даёт создать бота с 3–4 раза.\n"
    "4. BotFather напишет вам, что вы удачно создали бота, в середине сообщения будет токен. Он выглядит так:\n"
    "   123456789:YOUR_TELEGRAM_BOT_TOKEN\n"
    "5. Пришлите токен сюда\n\n"
    "В BotFather вы можете добавить аватарку и изменить описание вашему боту"
)


async def send_create_bot_instruction(message: Message) -> None:
    await message.answer(
        CREATE_BOT_INSTRUCTION_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Показать видео", callback_data="show_telegram_instruction_video")
        ]]),
    )


async def send_instruction_video(message: Message, kind: str, video_path, caption: str) -> None:
    file_id = get_instruction_file_id(kind)
    video = file_id
    if not video:
        if video_path.is_file():
            video = FSInputFile(video_path)
        else:
            logger.warning("%s instruction video is missing: %s", kind, video_path)
            await message.answer("Видеоинструкция временно недоступна.")
            return

    try:
        sent = await message.answer_video(
            video,
            caption=caption,
            supports_streaming=True,
        )
        if sent.video and sent.video.file_id and sent.video.file_id != file_id:
            save_instruction_file_id(kind, sent.video.file_id)
    except Exception as exc:
        logger.warning("Failed to send %s instruction video: %s", kind, exc)
        await message.answer("Не удалось отправить видеоинструкцию. Попробуйте нажать кнопку ещё раз.")


@router.callback_query(F.data == "show_telegram_instruction_video")
async def show_telegram_instruction_video(callback: CallbackQuery):
    await send_instruction_video(
        callback.message,
        "telegram",
        telegram_bot_instruction_video_path(),
        "Видеоинструкция по созданию Telegram-бота",
    )
    await callback.answer()


@router.callback_query(F.data == "create_bot")
async def create_bot(callback: CallbackQuery, state: FSMContext):
    await send_create_bot_instruction(callback.message)
    await state.set_state(CreateBotStates.waiting_for_token)
    await callback.answer()


@router.message(CreateBotStates.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    # Пользователь мог прислать не текст (фото/стикер) — не падаем, просим токен.
    if not message.text:
        await message.answer(
            "Пришлите токен бота обычным текстом.\n"
            "Пример: 123456789:YOUR_TELEGRAM_BOT_TOKEN"
        )
        return
    token = message.text.strip()
    master_telegram_id = message.from_user.id
    # Используем имя пользователя из Telegram, если есть
    master_name = message.from_user.first_name or None

    if not is_valid_telegram_token(token):
        # НЕ сбрасываем состояние: пользователь может сразу прислать исправленный
        # токен, и бот его примет (раньше state.clear() ломал повторный ввод).
        await message.answer(
            "❌ Неверный формат токена. Пришлите его ещё раз.\n"
            "Пример: 123456789:YOUR_TELEGRAM_BOT_TOKEN\n\n"
            "Или нажмите /start, чтобы вернуться в меню."
        )
        return

    await message.answer("⏳ Проверяю токен и создаю бота...")

    try:
        result = await bot_manager.create_bot(master_telegram_id, token, master_name)
        has_vk = await owner_has_vk_bot(master_telegram_id)
        await message.answer(
            f"✅ Бот успешно создан!\n\n"
            f"Бот: {result['username']}\n"
            f"Статус: {BOT_STATUS_LABELS.get(result['status'], result['status'])}\n\n"
            "Теперь вы можете протестировать своего бота, использовать его для записи, а также "
            "прикрепить бота ВКонтакте. "
            "Не забудьте в профиле открыть расписание, указав рабочие дни и диапазоны часов, "
            "иначе другие люди не будут видеть окна для записи.\n"
            "Пожалуйста, оплатите подписку в течение 2 часов, иначе бот будет удалён.",
            reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=True, has_vk_bot=has_vk)
        )
        logger.info(f"Bot created for master {master_telegram_id}: {result}")
    except ValueError as e:
        await message.answer(
            f"❌ Ошибка: {str(e)}\n\n"
            "Нажмите /start чтобы вернуться в меню."
        )
        logger.error(f"Failed to create bot for {master_telegram_id}: {e}")
    except Exception as e:
        await message.answer(
            f"❌ Произошла ошибка при создании бота",
            reply_markup=architect_menu_keyboard(user_id=message.from_user.id)
        )
        logger.error(f"Unexpected error creating bot: {e}")

    await state.clear()


@router.callback_query(F.data == "my_bots")
async def show_my_bots(callback: CallbackQuery):
    master_id = callback.from_user.id
    bots = await bot_manager.get_all_bots()
    my_bots = [b for b in bots if b["master_telegram_id"] == master_id]

    if not my_bots:
        text = "📋 У вас пока нет ботов.\n\nНажмите 'Создать бота' чтобы начать."
    else:
        lines = ["📋 Ваши боты:\n"]
        for bot in my_bots:
            status_emoji = "🟢" if bot["status"] == "running" else "🔴"
            lines.append(f"{status_emoji} {bot['username']} — {bot['status']}")
        text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="my_bots")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
            ])
        )
    except TelegramBadRequest as e:
        # «message is not modified» при повторном «Обновить» без изменений — не ошибка.
        if "not modified" not in str(e):
            raise
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=await main_menu_keyboard(callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "stop_bot")
async def stop_bot(callback: CallbackQuery, state: FSMContext):
    master_id = callback.from_user.id
    success = await bot_manager.stop_bot(master_id)
    if success:
        await callback.message.edit_text(
            "🛑 Бот остановлен",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id)
        )
    else:
        await callback.message.edit_text(
            "❌ Бот не найден",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id)
        )
    await callback.answer()


@router.callback_query(F.data == "restart_bot")
async def restart_bot(callback: CallbackQuery, state: FSMContext):
    master_id = callback.from_user.id
    try:
        result = await bot_manager.restart_bot(master_id)
        await callback.message.edit_text(
            f"🔄 Бот перезапущен: {result['username']}",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id)
        )
    except ValueError as e:
        await callback.message.edit_text(
            f"❌ {str(e)}",
            reply_markup=architect_menu_keyboard(user_id=callback.from_user.id)
        )
    await callback.answer()
