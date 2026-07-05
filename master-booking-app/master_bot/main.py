import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Добавляем корень проекта в path для импортов
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from backend.database import init_db
from backend.fsm_storage import create_fsm_storage
from master_bot.handlers.client import router as client_router, set_bot_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Запуск Master Bot"""
    # Инициализация БД
    await init_db()
    logger.info("Database initialized")

    # Токен бота - можно передать через аргумент или переменную окружения
    bot_token = sys.argv[1] if len(sys.argv) > 1 else None

    if not bot_token:
        logger.error("Bot token not provided! Usage: python main.py <BOT_TOKEN>")
        sys.exit(1)

    # Устанавливаем токен для использования в хендлерах
    set_bot_token(bot_token)

    # Настройка прокси для Telegram
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')

    if proxy_url:
        session = AiohttpSession(proxy=proxy_url)
        logger.info(f"Using proxy: {proxy_url}")
    else:
        session = AiohttpSession()
        logger.info("Starting bot without proxy")

    # Инициализация бота
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session
    )

    # Диспетчер с FSM
    dp = Dispatcher(storage=create_fsm_storage())

    # Регистрация роутеров
    dp.include_router(client_router)

    logger.info(f"Starting Master Bot with token: {bot_token[:10]}...")

    # Запуск с указанием всех типов обновлений (иначе Telegram кэширует allowed_updates и не присылает callback_query)
    # Также сбрасываем offset для получения всех callback_query
    try:
        await dp.start_polling(
            bot,
            reset_webhook=True,
            allowed_updates=["message", "callback_query"]
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
