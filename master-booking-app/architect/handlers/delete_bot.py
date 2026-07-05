from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from architect.keyboards.menu import architect_menu_keyboard
from architect.services.bot_manager import bot_manager
from backend.database import MasterBot, Subscription, async_session_maker

router = Router()


async def _owned_bots(master_telegram_id: int) -> list[MasterBot]:
    # Удалять можно ЛЮБОГО своего бота, в том числе замороженного или с истёкшей
    # подпиской — иначе такой бот застревал в базе навсегда.
    async with async_session_maker() as session:
        result = await session.execute(
            select(MasterBot)
            .where(MasterBot.master_telegram_id == master_telegram_id)
            .order_by(MasterBot.id)
        )
        return list(result.scalars().all())


async def _show_confirmation(callback: CallbackQuery, bot: MasterBot) -> None:
    await callback.message.edit_text(
        "🗑 <b>Удаление бота</b>\n\n"
        f"Вы уверены, что хотите удалить @{bot.username or bot.id}?\n\n"
        "Бот перестанет отвечать клиентам. Это действие нельзя отменить.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_bot_apply:{bot.id}")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="back_to_menu")],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "delete_bot_menu")
async def delete_bot_menu(callback: CallbackQuery):
    bots = await _owned_bots(callback.from_user.id)
    if not bots:
        await callback.message.edit_text(
            "🗑 У вас пока нет созданных ботов.",
            reply_markup=architect_menu_keyboard(callback.from_user.id),
        )
    elif len(bots) == 1:
        await _show_confirmation(callback, bots[0])
    else:
        await callback.message.edit_text(
            "🗑 <b>Удаление бота</b>\n\nВыберите, какой бот нужно удалить:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                *[
                    [InlineKeyboardButton(
                        text=f"🤖 @{bot.username or bot.id}",
                        callback_data=f"delete_bot_select:{bot.id}",
                    )]
                    for bot in bots
                ],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
            ]),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_bot_select:"))
async def delete_bot_select(callback: CallbackQuery):
    try:
        bot_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный бот", show_alert=True)
        return
    bot = next((item for item in await _owned_bots(callback.from_user.id) if item.id == bot_id), None)
    if not bot:
        await callback.answer("Бот не найден", show_alert=True)
        return
    await _show_confirmation(callback, bot)
    await callback.answer()


@router.callback_query(F.data.startswith("delete_bot_apply:"))
async def delete_bot_apply(callback: CallbackQuery):
    try:
        bot_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный бот", show_alert=True)
        return
    deleted = await bot_manager.delete_bot(callback.from_user.id, bot_id)
    await callback.message.edit_text(
        "✅ Бот удалён." if deleted else "❌ Бот не найден.",
        reply_markup=architect_menu_keyboard(callback.from_user.id),
    )
    await callback.answer("Бот удалён" if deleted else "Бот не найден")
