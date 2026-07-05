import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from architect.keyboards.menu import architect_menu_keyboard, owner_has_vk_bot
from architect.handlers.create_bot import send_instruction_video
from architect.services.vk_bot_manager import vk_bot_manager
from backend.tutorial_media import vk_bot_instruction_video_path

logger = logging.getLogger(__name__)

router = Router()


class LinkVkStates(StatesGroup):
    waiting_for_token = State()


VK_INSTRUCTION = (
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


def vk_instruction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Показать видео", callback_data="show_vk_instruction_video")
    ]])


async def send_vk_instruction(message: Message) -> None:
    await message.answer(VK_INSTRUCTION, parse_mode="HTML", reply_markup=vk_instruction_keyboard())


@router.callback_query(F.data == "show_vk_instruction_video")
async def show_vk_instruction_video(callback: CallbackQuery):
    await send_instruction_video(
        callback.message,
        "vk",
        vk_bot_instruction_video_path(),
        "Видеоинструкция по созданию бота ВКонтакте",
    )
    await callback.answer()


@router.callback_query(F.data == "link_vk_bot")
async def link_vk_bot(callback: CallbackQuery, state: FSMContext):
    available = await vk_bot_manager.get_unlinked_telegram_bots(callback.from_user.id)
    if not available:
        await callback.answer("Нет Telegram-ботов, которым требуется привязка ВКонтакте.", show_alert=True)
        return
    if len(available) > 1:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"@{item['username'].lstrip('@')}",
                callback_data=f"link_vk_target:{item['id']}",
            )]
            for item in available
        ])
        await callback.message.answer(
            "Выберите Telegram-бота, к которому нужно подключить ВКонтакте:",
            reply_markup=keyboard,
        )
        await callback.answer()
        return
    await state.update_data(master_bot_id=available[0]["id"])
    await send_vk_instruction(callback.message)
    await state.set_state(LinkVkStates.waiting_for_token)
    await callback.answer()


@router.callback_query(F.data.startswith("link_vk_target:"))
async def select_vk_target(callback: CallbackQuery, state: FSMContext):
    try:
        master_bot_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректный выбор.", show_alert=True)
        return
    available = await vk_bot_manager.get_unlinked_telegram_bots(callback.from_user.id)
    if master_bot_id not in {item["id"] for item in available}:
        await callback.answer("Этот бот уже связан или недоступен.", show_alert=True)
        return
    await state.update_data(master_bot_id=master_bot_id)
    await state.set_state(LinkVkStates.waiting_for_token)
    await send_vk_instruction(callback.message)
    await callback.answer()


@router.message(LinkVkStates.waiting_for_token)
async def process_vk_token(message: Message, state: FSMContext):
    token = (message.text or "").strip()
    if not token.startswith("vk1."):
        await message.answer(
            "❌ Это не похоже на ключ сообщества ВКонтакте. Он начинается с <code>vk1.</code>\n"
            "Скопируйте ключ из настроек сообщества и отправьте ещё раз, или нажмите /start.",
            parse_mode="HTML",
        )
        return

    await message.answer("⏳ Проверяю ключ и создаю бота ВКонтакте...")
    try:
        state_data = await state.get_data()
        result = await vk_bot_manager.create_vk_bot(
            message.from_user.id,
            token,
            master_bot_id=state_data.get("master_bot_id"),
        )
        group_url = f"https://vk.com/club{result['group_id']}"
        await message.answer(
            f"✅ Бот успешно создан!\n\n"
            f"Бот: {result['group_name']}\n"
            f"Ссылка для клиентов: {group_url}\n"
            f"Статус: Работает\n\n"
            "Теперь вы можете протестировать своего бота, использовать его для записи, а также "
            "прикрепить бота Telegram. Не забудьте в профиле открыть расписание, указав рабочие "
            "дни и диапазоны часов, иначе другие люди не будут видеть окна для записи.\n"
            f"Откройте {group_url} и нажмите «Начать», чтобы бот мог присылать вам уведомления о записях.\n"
            "Пожалуйста, оплатите подписку в течение 2 часов, иначе бот будет удалён.",
            reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=True, has_vk_bot=True),
        )
        logger.info("VK bot created for master %s: %s", message.from_user.id, result)
    except ValueError as e:
        await message.answer(f"❌ {e}\n\nИсправьте и отправьте ключ снова, или нажмите /start.")
    except Exception as e:
        logger.exception("Failed to create VK bot for %s", message.from_user.id)
        has_vk = await owner_has_vk_bot(message.from_user.id)
        await message.answer(
            "❌ Не удалось создать бота ВКонтакте. Попробуйте позже или нажмите /start.",
            reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=True, has_vk_bot=has_vk),
        )
    await state.clear()
