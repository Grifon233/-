"""Сборщик-юзербот (см. docs/01, docs/02).

Аккаунты Telethon (каждый через свой прокси) вступают в источники по инвайт-ссылкам
и пересылают новые сообщения на backend POST /ingest.

Запуск:
    cd collector
    python -m venv .venv && . .venv/Scripts/activate
    pip install -r requirements.txt
    cp accounts.example.yml accounts.yml   # заполнить аккаунты+прокси
    cp sources.example.yml sources.yml     # заполнить источники
    python main.py

ВАЖНО: каждый аккаунт обязан иметь прокси (правило проекта). Без прокси скрипт не подключает аккаунт.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from telethon.errors import UserAlreadyParticipantError, FloodWaitError
from telethon import TelegramClient, events, utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

load_dotenv(Path(__file__).with_name(".env"))

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")
ALLOW_INTERACTIVE_LOGIN = os.environ.get("ALLOW_INTERACTIVE_LOGIN") == "1"
DEAD_LETTER_FILE = Path(os.environ.get("DEAD_LETTER_FILE", "failed_ingest.jsonl"))
logger = logging.getLogger("collector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _build_proxy(p: dict):
    """Telethon proxy tuple. Прокси обязателен."""
    if not p:
        raise ValueError("У аккаунта нет прокси — подключение запрещено (правило проекта).")
    required = {"host", "port"}
    missing = required - set(p)
    if missing:
        raise ValueError(f"В прокси отсутствуют поля: {', '.join(sorted(missing))}")
    import socks
    kind = socks.SOCKS5 if p.get("type") == "socks5" else socks.HTTP
    return (kind, p["host"], int(p["port"]), True, p.get("username"), p.get("password"))


async def _join(client: TelegramClient, invite: str, max_attempts: int = 3):
    """Вступить по инвайт-ссылке или @username."""
    for attempt in range(max_attempts):
        try:
            if "+" in invite or "joinchat" in invite:
                hash_ = invite.rsplit("/", 1)[-1].lstrip("+")
                updates = await client(ImportChatInviteRequest(hash_))
                if updates.chats:
                    return updates.chats[0]
            else:
                entity = await client.get_entity(invite)
                await client(JoinChannelRequest(entity))
                return entity
        except UserAlreadyParticipantError:
            return await client.get_entity(invite)
        except FloodWaitError as exc:
            if attempt == max_attempts - 1:
                raise
            logger.warning("FloodWait %ss при вступлении в %s", exc.seconds, invite)
            await asyncio.sleep(exc.seconds)
    return await client.get_entity(invite)


async def _send_to_backend(text: str, chat: str, msg_id: int, link: str, ts, city: str):
    payload = {
        "source_chat": chat, "message_id": msg_id, "message_link": link,
        "text": text, "ts": ts.isoformat(), "city": city,
    }
    headers = {"X-API-Key": INGEST_API_KEY} if INGEST_API_KEY else {}
    async with httpx.AsyncClient(timeout=20) as http:
        delay = 1
        last_error = ""
        for attempt in range(4):
            try:
                response = await http.post(
                    f"{BACKEND_URL.rstrip('/')}/ingest",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                return True
            except httpx.HTTPError as exc:
                last_error = str(exc)
                if attempt < 3:
                    await asyncio.sleep(delay)
                    delay *= 2
    logger.error("Ingest permanently failed for %s/%s: %s", chat, msg_id, last_error)
    try:
        with DEAD_LETTER_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Cannot write dead-letter file")
    return False


async def run_account(acc: dict, sources: list[dict]):
    proxy = _build_proxy(acc.get("proxy"))
    client = TelegramClient(acc["session"], acc["api_id"], acc["api_hash"], proxy=proxy)
    if ALLOW_INTERACTIVE_LOGIN:
        await client.start(phone=acc["phone"])
    else:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                f"[{acc['name']}] сессия не авторизована; выполните первый вход "
                "локально с ALLOW_INTERACTIVE_LOGIN=1"
            )
    logger.info("[%s] вошёл", acc["name"])

    # вступаем в назначенные источники
    src_by_city: dict[int, str] = {}
    for s in sources:
        if s.get("assigned_account") != acc["name"]:
            continue
        ent = await _join(client, s["invite"])
        src_by_city[utils.get_peer_id(ent)] = s["city"]
        await asyncio.sleep(2)  # антифлуд

    @client.on(events.NewMessage)
    async def handler(event):
        city = src_by_city.get(event.chat_id)
        if city is None or not event.raw_text:
            return
        username = getattr(event.chat, "username", None)
        link = f"https://t.me/{username}/{event.id}" if username else f"chat:{event.chat_id}/{event.id}"
        await _send_to_backend(event.raw_text, str(event.chat_id), event.id, link, event.message.date, city)

    logger.info("[%s] слушает %s источников", acc["name"], len(src_by_city))
    await client.run_until_disconnected()


async def _run_account_guarded(acc: dict, sources: list[dict]) -> None:
    try:
        await run_account(acc, sources)
    except Exception:
        logger.exception("Аккаунт %s остановлен, остальные продолжают работу", acc.get("name"))


async def main():
    with open("accounts.yml", encoding="utf-8") as f:
        accounts = yaml.safe_load(f)["accounts"]
    with open("sources.yml", encoding="utf-8") as f:
        sources = yaml.safe_load(f)["sources"]
    await asyncio.gather(*(_run_account_guarded(a, sources) for a in accounts))


if __name__ == "__main__":
    asyncio.run(main())
