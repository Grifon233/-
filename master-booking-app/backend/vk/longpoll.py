"""Bots Long Poll супервизор для VK-ботов мастеров.

Зеркало backend.webhook.run_master_bot_polling: следит за running VkBot в БД и
держит по одной задаче Long Poll на каждое сообщество. Принятые message_new
передаёт в backend.vk.bot.handle_vk_message.
"""
import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import suppress

import httpx
from sqlalchemy import select, update

from backend.database import async_session_maker, VkBot
from backend.token_utils import decrypt_token
from backend.vk import api
from backend.vk.bot import handle_vk_message
from backend.vk.architect_bot import handle_vk_architect_message

logger = logging.getLogger(__name__)

_LONG_POLL_WAIT = 25
_SUPERVISOR_INTERVAL = 10

# Защита от повторной обработки одного и того же сообщения: VK Long Poll иногда
# доставляет событие дважды (повторы при переустановке ключа, дубль-строки бота
# на одном сообществе и т.п.). Без дедупликации клиент получал ответ дважды.
_SEEN_TTL_SECONDS = 300
_SEEN_MAX = 4000
_seen_messages: "OrderedDict[tuple, float]" = OrderedDict()


def _already_processed(group_id: int, message: dict) -> bool:
    msg_id = message.get("conversation_message_id") or message.get("id")
    if not msg_id:
        return False
    key = (group_id, message.get("from_id"), msg_id)
    now = time.monotonic()
    while _seen_messages:
        oldest_key, oldest_ts = next(iter(_seen_messages.items()))
        if oldest_ts >= now - _SEEN_TTL_SECONDS:
            break
        _seen_messages.popitem(last=False)
    if key in _seen_messages:
        return True
    _seen_messages[key] = now
    while len(_seen_messages) > _SEEN_MAX:
        _seen_messages.popitem(last=False)
    return False


# Коды VK API, означающие, что токен сообщества больше не действует
# (отозван, удалён или невалиден). Такие боты нельзя опрашивать заново —
# помечаем "error" и уведомляем владельца, иначе супервизор бесконечно
# перезапускал опрос ВСЕХ VK-ботов из-за одного мёртвого.
_PERMANENT_AUTH_ERROR_CODES = {5, 27, 28}


async def _mark_status(vk_bot_id: int, status: str) -> None:
    async with async_session_maker() as session:
        await session.execute(update(VkBot).where(VkBot.id == vk_bot_id).values(status=status))
        await session.commit()


async def _notify_owner_vk_bot_broken(vk_bot_id: int) -> None:
    """Best-effort: сообщить владельцу в Telegram, что VK-бот потерял доступ."""
    try:
        from architect.config import settings
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
    except Exception:
        return
    if not settings.architect_token or ":" not in settings.architect_token:
        return
    async with async_session_maker() as session:
        vk_bot = await session.get(VkBot, vk_bot_id)
    if not vk_bot or not vk_bot.master_telegram_id or vk_bot.master_telegram_id <= 0:
        return
    proxy_url = None
    import os
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or settings.proxy_url
    aio_session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
    tg_bot = Bot(token=settings.architect_token, session=aio_session)
    group_label = vk_bot.group_name or f"сообщества #{vk_bot.group_id}"
    try:
        await tg_bot.send_message(
            vk_bot.master_telegram_id,
            "⚠️ Бот ВКонтакте перестал работать.\n\n"
            f"Токен {group_label} больше не действует (сообщество отозвало доступ). "
            "Клиенты не смогут записаться через ВКонтакте. "
            "Чтобы восстановить, заново привяжите бота ВКонтакте в Архитекторе (/start).",
            request_timeout=20,
        )
    except Exception as exc:
        logger.warning("Failed to notify owner about broken VK bot %s: %s", vk_bot_id, exc)
    finally:
        with suppress(Exception):
            await tg_bot.session.close()


async def _poll_one(vk_bot_id: int, token: str, group_id: int, bot_type: str = "client") -> None:
    """Бесконечный Long Poll одного сообщества с переустановкой ключа по failed."""
    server = key = ts = None

    async def refresh(reset_ts: bool) -> bool:
        nonlocal server, key, ts
        try:
            await api.ensure_long_poll_enabled(token, group_id)
            data = await api.get_long_poll_server(token, group_id)
            server, key = data["server"], data["key"]
            if reset_ts or ts is None:
                ts = data["ts"]
            return True
        except api.VkApiError as e:
            logger.error("VK bot %s: cannot get long poll server (code %s): %s", vk_bot_id, e.code, e.message)
            if e.code in _PERMANENT_AUTH_ERROR_CODES:
                # Токен мёртв — снимаем бота с опроса и уведомляем владельца,
                # чтобы не спамить VK и не дёргать перезапуск остальных ботов.
                await _mark_status(vk_bot_id, "error")
                await _notify_owner_vk_bot_broken(vk_bot_id)
                return False
            return False
        except Exception as e:
            logger.error("VK bot %s: long poll server error: %s", vk_bot_id, e)
            return False

    if not await refresh(reset_ts=True):
        await asyncio.sleep(30)
        return

    async with httpx.AsyncClient(timeout=_LONG_POLL_WAIT + 10) as client:
        while True:
            try:
                resp = await client.get(
                    server,
                    params={"act": "a_check", "key": key, "ts": ts, "wait": _LONG_POLL_WAIT},
                )
                data = resp.json()
            except Exception as e:
                logger.warning("VK bot %s: long poll request failed: %s", vk_bot_id, e)
                await asyncio.sleep(3)
                continue

            failed = data.get("failed")
            if failed == 1:
                ts = data.get("ts", ts)
                continue
            if failed in (2, 3):
                if not await refresh(reset_ts=(failed == 3)):
                    await asyncio.sleep(5)
                continue

            ts = data.get("ts", ts)
            for update_event in data.get("updates", []):
                if update_event.get("type") == "message_new":
                    try:
                        obj = update_event.get("object", {})
                        message_payload = obj.get("message") or obj
                        if _already_processed(group_id, message_payload):
                            continue
                        if bot_type == "architect":
                            await handle_vk_architect_message(group_id, obj, token)
                        else:
                            await handle_vk_message(group_id, obj)
                    except Exception:
                        logger.exception("VK bot %s: failed to handle message", vk_bot_id)


async def run_vk_bots_polling() -> None:
    """Супервизор: запускает/останавливает Long Poll-задачи под набор running VkBot."""
    tasks: dict[int, asyncio.Task] = {}
    signature = None
    try:
        while True:
            async with async_session_maker() as session:
                bots = (await session.execute(
                    select(VkBot).where(VkBot.status == "running").order_by(VkBot.id)
                )).scalars().all()
            next_signature = tuple((b.id, b.token, b.group_id, getattr(b, "bot_type", "client")) for b in bots)

            if next_signature != signature:
                # Останавливаем всё и поднимаем заново под актуальный набор.
                for task in tasks.values():
                    task.cancel()
                for task in tasks.values():
                    with suppress(asyncio.CancelledError):
                        await task
                tasks = {}
                for b in bots:
                    try:
                        raw = decrypt_token(b.token)
                    except Exception as e:
                        logger.error("VK bot %s: cannot decrypt token: %s", b.id, e)
                        continue
                    tasks[b.id] = asyncio.create_task(_poll_one(b.id, raw, b.group_id, getattr(b, "bot_type", "client")))
                signature = next_signature
                logger.info("VK long poll running for %s bot(s)", len(tasks))

            # Перезапуск упавших задач произойдёт при следующей смене signature;
            # сбрасываем его, если какая-то задача завершилась, чтобы поднять заново.
            if any(t.done() for t in tasks.values()):
                signature = None

            await asyncio.sleep(_SUPERVISOR_INTERVAL)
    finally:
        for task in tasks.values():
            task.cancel()
        for task in tasks.values():
            with suppress(asyncio.CancelledError):
                await task
