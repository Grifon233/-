import asyncio
import logging
import os
import time
from contextlib import suppress

from aiohttp import web
from fastapi import APIRouter, Request
from sqlalchemy import select

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import TokenBasedRequestHandler, setup_application

from backend.config import get_webhook_url
from backend.database import MasterBot, async_session_maker
from backend.fsm_storage import create_fsm_storage
from backend.handlers.master_bot import router as master_bot_router
from backend.token_utils import decrypt_token, mask_token

logger = logging.getLogger(__name__)

# Один dispatcher для всех созданных мастер-ботов.
webhook_dispatcher = Dispatcher(storage=create_fsm_storage())
webhook_dispatcher.include_router(master_bot_router)

PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

# FastAPI webhook для production. Telegram приходит на WEBHOOK_BASE_URL/api/webhook/{token}.
# Legacy /webhook/{token} оставлен для старых установленных webhook.
router = APIRouter()
_bot_cache: dict[str, Bot] = {}
_webhook_tasks: set[asyncio.Task] = set()

# Кэш проверенных токенов: токен из URL вебхука должен принадлежать
# зарегистрированному боту. Иначе любой мог бы заставить сервер создавать
# Bot-объекты на произвольные токены (рост памяти) и слать поддельные апдейты.
_MAX_BOT_CACHE = 500
_TOKEN_VALIDATION_TTL = 300
_validated_tokens: dict[str, float] = {}


async def _is_registered_bot_token(token: str) -> bool:
    now = time.time()
    cached = _validated_tokens.get(token)
    if cached and now - cached < _TOKEN_VALIDATION_TTL:
        return True
    async with async_session_maker() as session:
        bots = (await session.execute(select(MasterBot))).scalars().all()
    for master_bot in bots:
        if decrypt_token(master_bot.token) == token:
            _validated_tokens[token] = now
            return True
    return False


def _bot_settings() -> dict:
    settings = {"default": DefaultBotProperties(parse_mode=ParseMode.HTML)}
    if PROXY_URL:
        settings["session"] = AiohttpSession(proxy=PROXY_URL)
    return settings


def get_cached_bot(token: str) -> Bot:
    """Получить Bot по token для обработки webhook через FastAPI."""
    if token not in _bot_cache:
        # Защитный предел на случай неожиданного роста (токены валидируются выше).
        if len(_bot_cache) >= _MAX_BOT_CACHE:
            old_token, old_bot = _bot_cache.popitem()
            with suppress(Exception):
                asyncio.create_task(old_bot.session.close())
        _bot_cache[token] = Bot(token=token, **_bot_settings())
    return _bot_cache[token]


async def close_cached_bots() -> None:
    """Закрыть aiohttp-сессии cached Bot при shutdown."""
    for bot in list(_bot_cache.values()):
        await bot.session.close()
    _bot_cache.clear()


async def run_master_bot_polling() -> None:
    """Keep one outbound polling session for every running master bot."""
    if os.getenv("MASTER_BOT_DELIVERY", "polling").lower() in {"webhook", "webhooks"}:
        await run_master_bot_webhooks()
        return

    signature = None
    polling_task = None
    polling_bots: list[Bot] = []
    try:
        while True:
            if polling_task and polling_task.done():
                with suppress(Exception):
                    await polling_task
                for bot in polling_bots:
                    with suppress(Exception):
                        await bot.session.close()
                polling_task = None
                polling_bots = []
                signature = None
                logger.warning("Master bot polling stopped unexpectedly; retrying startup")

            async with async_session_maker() as session:
                bots = (await session.execute(
                    select(MasterBot).where(MasterBot.status == "running").order_by(MasterBot.id)
                )).scalars().all()
            next_signature = tuple((item.id, item.token) for item in bots)
            if next_signature != signature:
                if polling_task:
                    polling_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await polling_task
                for bot in polling_bots:
                    with suppress(Exception):
                        await bot.session.close()
                polling_bots = []
                transient_failures = 0
                for item in bots:
                    bot = None
                    try:
                        bot = Bot(token=decrypt_token(item.token), **_bot_settings())
                        await bot.get_me()
                        polling_bots.append(bot)
                    except TelegramUnauthorizedError:
                        logger.error("Master bot %s has invalid token; marking as error", item.id)
                        async with async_session_maker() as session:
                            db_bot = await session.get(MasterBot, item.id)
                            if db_bot and db_bot.status == "running":
                                db_bot.status = "error"
                                await session.commit()
                        if bot:
                            with suppress(Exception):
                                await bot.session.close()
                    except Exception as exc:
                        logger.error("Cannot start polling for master bot %s: %s", item.id, exc)
                        transient_failures += 1
                        if bot:
                            with suppress(Exception):
                                await bot.session.close()
                ready_bots = []
                for bot in polling_bots:
                    try:
                        await bot.delete_webhook(drop_pending_updates=False)
                        await bot.set_my_commands([BotCommand(command="start", description="Открыть меню")])
                        ready_bots.append(bot)
                    except Exception as exc:
                        logger.error("Cannot prepare master bot polling: %s", exc)
                        transient_failures += 1
                        with suppress(Exception):
                            await bot.session.close()
                polling_bots = ready_bots
                polling_task = asyncio.create_task(
                    webhook_dispatcher.start_polling(
                        *polling_bots,
                        allowed_updates=["message", "callback_query"],
                        handle_signals=False,
                        close_bot_session=False,
                    )
                ) if polling_bots else None
                # Transient Telegram/proxy failures must be retried. Invalid tokens
                # are marked as error above and naturally disappear from the next query.
                signature = next_signature if transient_failures == 0 else None
                logger.info("Master bot polling restarted for %s bot(s)", len(polling_bots))
            await asyncio.sleep(10)
    finally:
        if polling_task:
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
        for bot in polling_bots:
            await bot.session.close()


async def run_master_bot_webhooks() -> None:
    """Ensure every running master bot sends updates to this FastAPI app."""
    signature = None
    while True:
        async with async_session_maker() as session:
            bots = (await session.execute(
                select(MasterBot).where(MasterBot.status == "running").order_by(MasterBot.id)
            )).scalars().all()
        next_signature = tuple((item.id, item.token) for item in bots)
        if next_signature != signature:
            for item in bots:
                bot = None
                try:
                    raw_token = decrypt_token(item.token)
                    bot = Bot(token=raw_token, **_bot_settings())
                    await bot.get_me()
                    await bot.set_my_commands([BotCommand(command="start", description="Открыть меню")])
                    await bot.set_webhook(
                        get_webhook_url(raw_token),
                        allowed_updates=["message", "callback_query"],
                        drop_pending_updates=False,
                        request_timeout=10,
                    )
                except TelegramUnauthorizedError:
                    logger.error("Master bot %s has invalid token; marking as error", item.id)
                    async with async_session_maker() as session:
                        db_bot = await session.get(MasterBot, item.id)
                        if db_bot and db_bot.status == "running":
                            db_bot.status = "error"
                            await session.commit()
                except Exception as exc:
                    logger.error("Cannot configure webhook for master bot %s: %s", item.id, exc)
                finally:
                    if bot:
                        with suppress(Exception):
                            await bot.session.close()
            signature = next_signature
            logger.info("Master bot webhooks configured for %s bot(s)", len(bots))
        await asyncio.sleep(60)


async def _feed_fastapi_webhook(bot_token: str, update: dict) -> None:
    """Передать Telegram update в aiogram dispatcher."""
    bot = get_cached_bot(bot_token)
    try:
        result = await webhook_dispatcher.feed_webhook_update(bot, update)
        if result:
            await webhook_dispatcher.silent_call_request(bot=bot, result=result)
    except Exception as e:
        logger.exception(f"Webhook update failed for bot {mask_token(bot_token)}: {e}")


@router.post("/api/webhook/{bot_token}")
@router.post("/webhook/{bot_token}")
async def telegram_webhook(
    bot_token: str,
    request: Request,
) -> dict:
    """Webhook endpoint для всех ботов мастеров.

    Aiogram сам переносит долгие handlers в background после timeout.
    """
    # Токен в URL — это секрет вебхука. Принимаем апдейты только для
    # зарегистрированных ботов, чтобы не плодить Bot-объекты на чужие токены
    # и не принимать поддельные апдейты на незарегистрированные токены.
    if not await _is_registered_bot_token(bot_token):
        logger.warning("Webhook update for unregistered bot token %s ignored", mask_token(bot_token))
        return {"ok": True}

    update = await request.json()
    task = asyncio.create_task(_feed_fastapi_webhook(bot_token, update))
    _webhook_tasks.add(task)
    task.add_done_callback(_webhook_tasks.discard)
    return {"ok": True}


@router.get("/api/webhook/health/{bot_token}")
async def webhook_health(bot_token: str) -> dict:
    """Проверка, что публичный webhook endpoint видит master bot в БД.

    Telegram вызывает POST /webhook/{token}; этот GET нужен для диагностики
    nginx/WEBHOOK_BASE_URL перед установкой webhook.
    """
    async with async_session_maker() as session:
        result = await session.execute(select(MasterBot))
        bots = result.scalars().all()

    for master_bot in bots:
        if decrypt_token(master_bot.token) == bot_token:
            return {
                "ok": True,
                "bot_id": master_bot.id,
                "status": master_bot.status,
                "username": master_bot.username,
            }

    return {"ok": False, "error": "bot token is not registered"}


def setup_webhook(app: web.Application) -> None:
    """Настройка legacy aiohttp webhook handler, если он включён отдельно."""
    TokenBasedRequestHandler(
        dispatcher=webhook_dispatcher,
        handle_in_background=True,
        bot_settings=_bot_settings(),
    ).register(app, path="/webhook/{bot_token}")

    setup_application(app, webhook_dispatcher)


async def start_webhook_server():
    """Запуск legacy aiohttp сервера на 8081 для отдельных деплоев."""
    app = web.Application()
    setup_webhook(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8081)
    await site.start()

    logger.info("Webhook server started on port 8081")
    return runner


async def configure_webhook_for_bot(bot: Bot) -> None:
    """Настройка webhook для конкретного бота."""
    webhook_url = get_webhook_url(bot.token)
    await bot.set_webhook(
        webhook_url,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
        request_timeout=10,
    )
    logger.info(f"Webhook set for bot {mask_token(bot.token)}")
