import asyncio
import logging
import os
import sys
from pathlib import Path
from contextlib import suppress

# Add project root to sys.path for module imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import BotCommand

from architect.config import settings
from architect.handlers.start import router as start_router
from architect.handlers.create_bot import router as create_router
from architect.handlers.settings import router as settings_router
from architect.handlers.subscription import router as subscription_router
from architect.handlers.yookassa_payment import router as yookassa_router
from architect.handlers.admin_commands import router as admin_router, set_admin_bot
from architect.handlers.demo import router as demo_router
from architect.handlers.delete_bot import router as delete_bot_router
from architect.handlers.overview import router as overview_router
from architect.handlers.feedback import router as feedback_router
from architect.handlers.vk_bot import router as vk_bot_router
from architect.services.subscription_service import subscription_service
from backend.database import init_db
from backend.fsm_storage import create_fsm_storage

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

dp = Dispatcher(storage=create_fsm_storage())

dp.include_routers(start_router, create_router, settings_router, subscription_router, yookassa_router, admin_router, demo_router, delete_bot_router, overview_router, feedback_router, vk_bot_router)


@dp.message(Command("menu"))
async def cmd_menu(message):
    from architect.keyboards.menu import architect_menu_keyboard, owner_has_bot, owner_has_vk_bot
    has_bot = await owner_has_bot(message.from_user.id)
    has_vk_bot = await owner_has_vk_bot(message.from_user.id) if has_bot else False
    await message.answer("Главное меню:", reply_markup=architect_menu_keyboard(user_id=message.from_user.id, has_bot=has_bot, has_vk_bot=has_vk_bot))


async def main():
    # Architect uses lifecycle tables before its periodic tasks start.
    # Run idempotent schema upgrades here as well as in FastAPI startup.
    await init_db()

    # Настройка прокси для Telegram
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or settings.proxy_url
    
    if proxy_url:
        session = AiohttpSession(proxy=proxy_url)
        logging.info("Starting bot with configured Telegram proxy")
    else:
        session = AiohttpSession()
        logging.info("Starting bot without proxy")

    bot = Bot(token=settings.architect_token, session=session)
    await bot.set_my_commands([BotCommand(command="start", description="Открыть главное меню")])
    set_admin_bot(bot)

    logging.info("Bot polling started...")
    subscription_task = asyncio.create_task(check_subscriptions_periodically(bot))
    subscription_reconcile_task = asyncio.create_task(reconcile_subscription_access_periodically())
    trial_cleanup_task = asyncio.create_task(delete_expired_trial_bots_periodically(bot))
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "pre_checkout_query"])
    finally:
        subscription_task.cancel()
        subscription_reconcile_task.cancel()
        trial_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await subscription_task
        with suppress(asyncio.CancelledError):
            await subscription_reconcile_task
        with suppress(asyncio.CancelledError):
            await trial_cleanup_task


async def check_subscriptions_periodically(bot: Bot) -> None:
    """Send subscription reminders and freeze expired bots once per day."""
    while True:
        try:
            await subscription_service.check_and_remind(bot)
        except Exception:
            logging.exception("Subscription periodic check failed")
        await asyncio.sleep(24 * 60 * 60)


async def delete_expired_trial_bots_periodically(bot: Bot) -> None:
    """Remove unpaid test bots shortly after their two-hour trial expires."""
    while True:
        try:
            await subscription_service.delete_expired_unpaid_trial_bots(bot)
        except Exception:
            logging.exception("Trial bot cleanup failed")
        await asyncio.sleep(10 * 60)


async def reconcile_subscription_access_periodically() -> None:
    """Retry access restoration if Telegram or VK was temporarily unavailable during payment."""
    while True:
        try:
            await subscription_service.reconcile_active_subscription_access()
        except Exception:
            logging.exception("Subscription access reconciliation failed")
        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(main())
