import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart

from bot.config import BOT_TOKEN, TRAINER_ID, HTTPS_PROXY
from bot.models.database import init_db
from bot.handlers import common, poll, trainer, developer, fallback
from bot.services.scheduler import setup_scheduler
from bot.services.fsm_storage import SQLAlchemyFSMStorage

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    print("=" * 50)
    print("БОТ ЗАПУЩЕН")
    print("=" * 50)
    await bot.send_message(
        TRAINER_ID,
        "✅ Бот запущен и готов к работе!"
    )


async def main():
    """Главная функция запуска бота"""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не найден в .env")
        return

    # Инициализация базы данных
    init_db()
    print("✅ База данных инициализирована")

    # Создание бота и диспетчера
    session = None
    if HTTPS_PROXY:
        print(f"🌐 Использую прокси: {HTTPS_PROXY}")
        session = AiohttpSession(proxy=HTTPS_PROXY)
    
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = SQLAlchemyFSMStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация роутеров (от частного к общему)
    dp.include_router(developer.router)  # команды разработчика (/dev)
    dp.include_router(poll.router)       # обработка ответов на опрос
    dp.include_router(common.router)     # базовые команды (/start, /help)
    dp.include_router(trainer.router)    # команды тренера
    dp.include_router(fallback.router)   # обработка неизвестных сообщений

    # Настройка планировщика
    setup_scheduler(bot, storage)

    # Запуск
    logger.info("Бот запущен")
    print("=" * 50)
    print("Ожидание сообщений...")
    print("=" * 50)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        print("DEBUG: Polling completed normally")
    except Exception as e:
        logger.error(f"Бот завершил работу с ошибкой: {e}", exc_info=True)
        print(f"DEBUG: Exception in polling: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())