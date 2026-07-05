from aiogram import Router, F
from aiogram.types import Message
from bot.config import ATHLETES

router = Router()
router.message.filter(F.chat.type == "private")

@router.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений, которые не были пойманы другими роутерами"""
    # Если это команда, значит она неизвестна
    if message.text and message.text.startswith("/"):
        return

    telegram_id = message.from_user.id

    # Если пользователь не в списке разрешенных
    if telegram_id not in ATHLETES:
        await message.answer("У вас нет доступа к этому боту.")
    # Если пользователь в списке, но сообщение не распознано (например, неверный формат расписания)
    # то мы просто ничего не делаем или можем вывести подсказку.
    # Но для тренера лучше ничего не делать здесь, так как trainer.router сам выводит ошибку парсинга.
