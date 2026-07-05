"""
Обработчик управления ботами
"""
from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards.inline import (
    manage_bots_keyboard,
    bot_actions_keyboard,
    delete_confirmation_keyboard,
    main_menu_keyboard
)
from services.bot_manager import bot_manager
from texts import get_texts
from config import config


def register_handlers(dp: Dispatcher):
    """Регистрация обработчиков"""

    @dp.callback_query(F.data == "manage_bots")
    async def show_bots(callback: CallbackQuery):
        """Показать список ботов пользователя"""
        texts = get_texts()

        bots = await bot_manager.get_user_bots(callback.from_user.id)

        if not bots:
            await callback.message.edit_text(
                texts.manage_no_bots,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🤖 Создать нового бота",
                        callback_data="create_bot"
                    )],
                    [InlineKeyboardButton(
                        text="◀️ Назад",
                        callback_data="menu"
                    )]
                ])
            )
            await callback.answer()
            return

        # Формируем текст со списком ботов
        bots_text = f"<b>{texts.manage_title}</b>\n\n"
        for bot in bots:
            status = "⚡ Активен" if bot.is_active else "⏸️ Неактивен"
            bots_text += f"🤖 <b>@{bot.bot_username}</b>\n"
            bots_text += f"Мастер: {bot.master_name}\n"
            bots_text += f"Статус: {status}\n\n"

        await callback.message.edit_text(
            bots_text,
            parse_mode="HTML",
            reply_markup=manage_bots_keyboard(bots, config.web_panel_url)
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("bot_") | F.data.startswith("activate_") | F.data.startswith("deactivate_") | F.data.startswith("delete_"))
    async def bot_action(callback: CallbackQuery, state: FSMContext):
        """Действия с ботом"""
        texts = get_texts()
        data = callback.data

        if data.startswith("bot_"):
            bot_id = int(data[4:])
            bots = await bot_manager.get_user_bots(callback.from_user.id)
            bot = next((b for b in bots if b.id == bot_id), None)

            if not bot:
                await callback.answer("Бот не найден", show_alert=True)
                return

            status = "⚡ Активен" if bot.is_active else "⏸️ Неактивен"

            text = f"<b>@{bot.bot_username}</b>\n\n"
            text += f"Мастер: {bot.master_name}\n"
            text += f"Сфера: {bot.profession}\n"
            text += f"Локация: {bot.location or 'Не указана'}\n"
            text += f"Статус: {status}\n"

            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=bot_actions_keyboard(bot.id, bot.is_active, config.web_panel_url)
            )

        elif data.startswith("activate_"):
            bot_id = int(data[9:])
            success = await bot_manager.activate_bot(bot_id)

            if success:
                await callback.answer("✅ Бот активирован")
                # Обновляем кнопки
                await bot_action(
                    CallbackQuery(
                        id=callback.id,
                        from_user=callback.from_user,
                        message=callback.message,
                        data=f"bot_{bot_id}",
                        chat_instance=callback.chat_instance,
                        inline_message_id=callback.inline_message_id,
                        game_short_name=callback.game_short_name
                    ),
                    state
                )
            else:
                await callback.answer("❌ Ошибка активации", show_alert=True)

        elif data.startswith("deactivate_"):
            bot_id = int(data[11:])
            success = await bot_manager.deactivate_bot(bot_id)

            if success:
                await callback.answer("⏸️ Бот деактивирован")
                # Обновляем кнопки
                await bot_action(
                    CallbackQuery(
                        id=callback.id,
                        from_user=callback.from_user,
                        message=callback.message,
                        data=f"bot_{bot_id}",
                        chat_instance=callback.chat_instance,
                        inline_message_id=callback.inline_message_id,
                        game_short_name=callback.game_short_name
                    ),
                    state
                )
            else:
                await callback.answer("❌ Ошибка деактивации", show_alert=True)

        elif data.startswith("delete_") and not data.startswith("confirm_delete_"):
            bot_id = int(data[7:])
            bots = await bot_manager.get_user_bots(callback.from_user.id)
            bot = next((b for b in bots if b.id == bot_id), None)

            if not bot:
                await callback.answer("Бот не найден", show_alert=True)
                return

            await callback.message.edit_text(
                texts.manage_delete_confirm.format(username=bot.bot_username),
                parse_mode="HTML",
                reply_markup=delete_confirmation_keyboard(bot.id, bot.bot_username)
            )

        elif data.startswith("confirm_delete_"):
            bot_id = int(data[14:])
            success = await bot_manager.delete_bot(bot_id)

            if success:
                await callback.message.edit_text(
                    "✅ Бот удалён",
                    reply_markup=main_menu_keyboard()
                )
                await callback.answer("Бот удалён")
            else:
                await callback.answer("❌ Ошибка удаления", show_alert=True)

        await callback.answer()


# Импорт для inline keyboard
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton