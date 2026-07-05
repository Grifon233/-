from html import escape
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from architect.keyboards.menu import architect_menu_keyboard

router = Router()
SUPERADMIN_ID = 623597334


class FeedbackStates(StatesGroup):
    waiting_for_message = State()


FEEDBACK_USER_ID_RE = re.compile(r"ID:\s*(?:<code>)?(\d+)")


@router.callback_query(F.data == "feedback")
async def request_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer(
        "Напишите мне суть вашего вопроса, и я передам его разработчикам. Это может быть сообщение о баге, "
        "пожелание, предложение или что угодно другое, что вы хотели бы сообщить."
    )
    await state.set_state(FeedbackStates.waiting_for_message)
    await callback.answer()


@router.message(FeedbackStates.waiting_for_message, F.text)
async def forward_feedback(message: Message, state: FSMContext) -> None:
    user = message.from_user
    profile_url = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    display_name = escape(user.full_name or "Пользователь")
    username = f"@{escape(user.username)}" if user.username else "логин не указан"
    await message.bot.send_message(
        SUPERADMIN_ID,
        "💬 <b>Новая обратная связь</b>\n\n"
        f"Отправитель: <a href=\"{profile_url}\">{display_name}</a>\n"
        f"Telegram: {username}\n"
        f"ID: <code>{user.id}</code>\n\n"
        "Ответьте на это сообщение реплаем, чтобы бот отправил ответ пользователю.\n\n"
        f"{escape(message.text)}",
        parse_mode="HTML",
    )
    await state.clear()
    await message.answer(
        "Уже отправил. Ваше сообщение будет учтено. Если ваш запрос предполагает обратную связь, "
        "с вами свяжутся в ближайшее время.",
        reply_markup=architect_menu_keyboard(user_id=user.id),
    )


@router.message(F.reply_to_message, F.text)
async def reply_to_feedback(message: Message) -> None:
    if message.from_user.id != SUPERADMIN_ID:
        return

    source_text = message.reply_to_message.html_text or message.reply_to_message.text or ""
    if "Новая обратная связь" not in source_text:
        return

    match = FEEDBACK_USER_ID_RE.search(source_text)
    if not match:
        await message.answer("Не удалось определить автора обращения.")
        return

    await message.bot.send_message(
        int(match.group(1)),
        "💬 <b>Ответ по вашему обращению</b>\n\n"
        f"{escape(message.text)}",
        parse_mode="HTML",
    )
    await message.answer("Ответ отправлен пользователю.")


@router.message(FeedbackStates.waiting_for_message)
async def reject_non_text_feedback(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте сообщение обычным текстом.")
