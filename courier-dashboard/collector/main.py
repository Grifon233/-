"""Forward new messages from configured, authorized Telegram sources to Courier Dashboard."""

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from ipaddress import IPv6Address
import json
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx
import yaml
from dotenv import load_dotenv
from python_socks import ProxyType
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, InviteRequestSentError, RPCError, UserAlreadyParticipantError
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest

BASE_DIR = Path(__file__).resolve().parent
WORKERS = 4
MAX_PENDING_MESSAGES = 500
MAX_RETRY_AFTER = 60
logger = logging.getLogger("collector")


class CollectorError(ValueError):
    """An actionable error safe to show without dumping secrets or source content."""


@dataclass(frozen=True)
class Config:
    backend_url: str
    ingest_api_key: str
    allow_interactive_login: bool
    dead_letter_file: Path | None


def _required_text(record: dict, key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise CollectorError(f"поле {key}: ожидается непустая строка без управляющих символов")
    return value.strip()


def _positive_int(value, field: str, maximum: int) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= maximum:
        raise CollectorError(f"поле {field}: ожидается целое число от 1 до {maximum}")
    return value


def _build_proxy(proxy) -> dict:
    if not isinstance(proxy, dict) or not proxy:
        raise CollectorError("прокси обязателен; без него подключение запрещено")
    kind = _required_text(proxy, "type").lower()
    protocols = {"socks5": ProxyType.SOCKS5, "http": ProxyType.HTTP}
    if kind not in protocols:
        raise CollectorError("поле proxy.type: укажите socks5 или http")
    host = _required_text(proxy, "host")
    if any(c.isspace() or c in "/@[]" for c in host):
        raise CollectorError("поле proxy.host: укажите только имя хоста или IP без схемы и учётных данных")
    if ":" in host:
        try:
            IPv6Address(host)
        except ValueError:
            raise CollectorError("поле proxy.host: укажите порт отдельно в proxy.port") from None
    # python-socks is declared in requirements.txt and is natively supported by Telethon.
    result = {
        "proxy_type": protocols[kind], "addr": host,
        "port": _positive_int(proxy.get("port"), "proxy.port", 65535), "rdns": True,
    }
    for field in ("username", "password"):
        value = proxy.get(field)
        if value is not None and not isinstance(value, str):
            raise CollectorError(f"поле proxy.{field}: ожидается строка")
        result[field] = value
    if bool(result["username"]) != bool(result["password"]):
        raise CollectorError("поля proxy.username и proxy.password должны быть заданы вместе")
    return result


def _load_yaml(path: Path, key: str) -> list[dict]:
    try:
        with path.open(encoding="utf-8-sig") as file:
            data = yaml.safe_load(file)
    except OSError as exc:
        raise CollectorError(f"не удалось прочитать {path} ({type(exc).__name__})") from None
    except (UnicodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f", строка {mark.line + 1}" if mark else ""
        raise CollectorError(f"неверный YAML в {path}{line}") from None
    records = data.get(key) if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        raise CollectorError(f"{path}: нужен непустой список {key}")
    return records


def _parse_source(invite: str) -> tuple[str, bool]:
    reference, is_invite = utils.parse_username(invite)
    if not reference or (is_invite and not re.fullmatch(r"[A-Za-z0-9_-]+", reference)):
        raise CollectorError("поле invite: требуется @username или корректная инвайт-ссылка Telegram")
    return reference, is_invite


def _load_configs(accounts_file: Path, sources_file: Path) -> tuple[dict, dict]:
    accounts = {}
    sessions = set()
    for index, record in enumerate(_load_yaml(accounts_file, "accounts"), 1):
        try:
            if not isinstance(record, dict):
                raise CollectorError("ожидается объект аккаунта")
            name = _required_text(record, "name")
            if name in accounts:
                raise CollectorError("имя аккаунта уже используется")
            session = Path(_required_text(record, "session")).expanduser()
            if not str(session).endswith(".session"):
                session = session.with_name(session.name + ".session")
            session = (accounts_file.resolve().parent / session).resolve()
            if session.is_dir():
                raise CollectorError("поле session должно указывать на файл, а не на каталог")
            if session in sessions:
                raise CollectorError("один файл сессии нельзя разделять между аккаунтами")
            api_id = _positive_int(record.get("api_id"), "api_id", 2**31 - 1)
            api_hash = _required_text(record, "api_hash")
            if not re.fullmatch(r"[0-9A-Fa-f]{32}", api_hash):
                raise CollectorError("поле api_hash: ожидается строка из 32 шестнадцатеричных цифр")
            phone = _required_text(record, "phone") if "phone" in record else None
            accounts[name] = {"session": session, "api_id": api_id, "api_hash": api_hash,
                              "phone": phone, "proxy": _build_proxy(record.get("proxy"))}
            sessions.add(session)
        except (OSError, ValueError) as exc:
            detail = str(exc) if isinstance(exc, CollectorError) else "неверный путь к файлу сессии"
            raise CollectorError(f"{accounts_file}: accounts[{index}] — {detail}") from None

    sources = defaultdict(list)
    seen = set()
    for index, record in enumerate(_load_yaml(sources_file, "sources"), 1):
        try:
            if not isinstance(record, dict):
                raise CollectorError("ожидается объект источника")
            name = _required_text(record, "assigned_account")
            if name not in accounts:
                raise CollectorError("assigned_account не соответствует ни одному аккаунту")
            city = _required_text(record, "city")
            if len(city) > 100:
                raise CollectorError("поле city: допускается не более 100 символов")
            reference, is_invite = _parse_source(_required_text(record, "invite"))
            key = (reference, is_invite)
            if key in seen:
                raise CollectorError("один источник нельзя указывать несколько раз")
            sources[name].append((index, reference, is_invite, city))
            seen.add(key)
        except CollectorError as exc:
            raise CollectorError(f"{sources_file}: sources[{index}] — {exc}") from None
    return accounts, sources


def _load_settings() -> Config:
    backend_url = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    try:
        parsed = urlsplit(backend_url)
        port = parsed.port  # Raises ValueError for a malformed port.
        normalized_url = httpx.URL(backend_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or port == 0 or any(c.isspace() or ord(c) < 32 or c in "?#\\" for c in backend_url)):
            raise ValueError
    except (ValueError, httpx.InvalidURL):
        raise CollectorError("BACKEND_URL: укажите абсолютный HTTP(S) URL без учётных данных, запроса или фрагмента") from None
    is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not is_loopback:
        raise CollectorError("BACKEND_URL: для удалённого backend требуется HTTPS")
    key = os.environ.get("INGEST_API_KEY", "").strip()
    if key and not re.fullmatch(r"[!-~]+", key):
        raise CollectorError("INGEST_API_KEY: используйте ASCII-символы без пробелов")
    local_demo = os.environ.get("INGEST_ALLOW_UNAUTHENTICATED") == "1" and is_loopback
    if not key and not local_demo:
        raise CollectorError("установите тот же INGEST_API_KEY, что и у backend")
    dead_letter = os.environ.get("DEAD_LETTER_FILE", "").strip()
    return Config(str(normalized_url).rstrip("/"), key, os.environ.get("ALLOW_INTERACTIVE_LOGIN") == "1",
                  Path(dead_letter).expanduser() if dead_letter else None)


async def _join(client: TelegramClient, reference: str, is_invite: bool):
    """Resolve an approved membership, or request to join via the configured reference."""
    if is_invite:
        previous = await client(CheckChatInviteRequest(reference))
        if isinstance(previous, types.ChatInviteAlready):
            return previous.chat
        try:
            await client(ImportChatInviteRequest(reference))
        except UserAlreadyParticipantError:
            pass  # Membership changed between the check and the import.
        current = await client(CheckChatInviteRequest(reference))
        if isinstance(current, types.ChatInviteAlready):
            return current.chat
        raise CollectorError("Telegram не подтвердил участие в источнике")

    entity = await client.get_entity(reference)
    if not isinstance(entity, types.Channel):
        raise CollectorError("публичный username не принадлежит группе или каналу")
    if entity.left:
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass
    return entity


def _retry_delay(header: str | None, attempt: int) -> float:
    delay = float(2**attempt)
    if header:
        try:
            seconds = header.strip()
            if re.fullmatch(r"[0-9]+", seconds):
                significant = seconds.lstrip("0") or "0"
                wait = float(significant) if len(significant) <= 9 else MAX_RETRY_AFTER + 1
            else:
                date = parsedate_to_datetime(header)
                wait = (date - datetime.now(timezone.utc)).total_seconds()
            delay = max(delay, wait)
        except (TypeError, ValueError, OverflowError):
            pass
    return delay


async def _post_ingest(http: httpx.AsyncClient, url: str, payload: dict) -> str | None:
    """Return an operator-readable failure label, or None on successful delivery."""
    for attempt in range(4):
        retry_after = None
        try:
            response = await http.post(url, json=payload)
        except httpx.RequestError as exc:
            error = type(exc).__name__
        else:
            status = response.status_code
            if response.is_success:
                # Extraction rejections (not a sighting, stale message, etc.) are intentional.
                try:
                    result = response.json()
                except ValueError:
                    return "некорректный ответ /ingest (не JSON)"
                return None if isinstance(result, dict) and type(result.get("accepted")) is bool else (
                    "некорректный ответ /ingest (нет поля accepted)"
                )
            error = f"HTTP {status}"
            if status not in {408, 429, 500, 502, 503, 504}:
                return error
            retry_after = response.headers.get("Retry-After")
        delay = _retry_delay(retry_after, attempt)
        if attempt < 3 and delay <= MAX_RETRY_AFTER:
            await asyncio.sleep(delay)
        else:
            return error
    raise AssertionError("unreachable")


class Delivery:
    def __init__(self, http: httpx.AsyncClient, config: Config):
        self.http = http
        self.url = f"{config.backend_url}/ingest"
        self.dead_letter_file = config.dead_letter_file
        self.queue = asyncio.Queue(maxsize=MAX_PENDING_MESSAGES)

    def _fail(self, payload: dict, reason: str) -> None:
        logger.error("Сообщение %s/%s не доставлено: %s", payload["source_chat"], payload["message_id"], reason)
        if self.dead_letter_file is None:
            return
        try:
            # Do not follow symlinks where supported. New files are owner-only on POSIX.
            descriptor = os.open(self.dead_letter_file, os.O_APPEND | os.O_CREAT | os.O_WRONLY
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error("Не удалось записать DEAD_LETTER_FILE (%s)", type(exc).__name__)

    def submit(self, payload: dict) -> None:
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._fail(payload, "очередь доставки переполнена")

    async def worker(self) -> None:
        while True:
            payload = await self.queue.get()
            try:
                error = await _post_ingest(self.http, self.url, payload)
                if error is not None:
                    self._fail(payload, error)
            except asyncio.CancelledError:
                self._fail(payload, "остановка сборщика до подтверждения доставки")
                raise
            finally:
                self.queue.task_done()

    async def close(self, workers: list[asyncio.Task]) -> None:
        try:
            await asyncio.wait_for(self.queue.join(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Не удалось опустошить очередь за 10 секунд")
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            while not self.queue.empty():
                self._fail(self.queue.get_nowait(), "остановка сборщика")
                self.queue.task_done()


def _event_payload(event, city: str, fallback_username: str | None) -> dict | None:
    if getattr(event.message, "noforwards", False) or getattr(event.chat, "noforwards", False):
        return None
    text = (event.raw_text or "").strip()
    if not text:
        return None
    stamp = event.message.date
    if len(text) > 10000 or event.id <= 0 or stamp is None or stamp.utcoffset() is None:
        logger.warning("Отброшено некорректное сообщение %s/%s", event.chat_id, event.id)
        return None
    # If the event contains the entity, use its current username (possibly removed).
    username = getattr(event.chat, "username", None) if event.chat is not None else fallback_username
    link = f"https://t.me/{username}/{event.id}" if username else f"chat:{event.chat_id}/{event.id}"
    return {"source_chat": str(event.chat_id), "message_id": event.id, "message_link": link,
            "text": text, "ts": stamp.isoformat(), "city": city}


async def _run_account(name: str, account: dict, sources: list, config: Config,
                       delivery: Delivery, login_lock: asyncio.Lock) -> None:
    session = account["session"]
    session.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    client = TelegramClient(str(session), account["api_id"], account["api_hash"],
                            proxy=account["proxy"], flood_sleep_threshold=0)
    registered: dict[int, tuple[str, str | None]] = {}

    @client.on(events.NewMessage)
    async def handle(event):
        source = registered.get(event.chat_id)
        if source is not None and (payload := _event_payload(event, *source)) is not None:
            delivery.submit(payload)

    try:
        if config.allow_interactive_login:
            async with login_lock:
                await client.start(phone=account["phone"])
        else:
            await client.connect()
            if not await client.is_user_authorized():
                raise CollectorError("сессия не авторизована; сначала войдите с ALLOW_INTERACTIVE_LOGIN=1")

        for index, (number, reference, is_invite, city) in enumerate(sources):
            if index:
                await asyncio.sleep(2)
            try:
                entity = await _join(client, reference, is_invite)
                if getattr(entity, "noforwards", False):
                    raise CollectorError("источник запрещает пересылку сообщений")
                peer_id = utils.get_peer_id(entity)
                if peer_id in registered:
                    raise CollectorError("источник уже зарегистрирован по другой ссылке")
                registered[peer_id] = (city, getattr(entity, "username", None))
            except InviteRequestSentError:
                logger.warning("[%s] источнику №%d нужно одобрение администратором; после него перезапустите сборщик",
                               name, number)
            except FloodWaitError as exc:
                logger.warning("[%s] Telegram ограничил запросы на %s с; новые источники временно не подключаются",
                               name, exc.seconds)
                break  # Do not retry other joins on this account under a Telegram rate limit.
            except (RPCError, ValueError) as exc:
                detail = str(exc) if isinstance(exc, CollectorError) else type(exc).__name__
                logger.warning("[%s] источник №%d пропущен: %s", name, number, detail)
        if not registered:
            raise CollectorError("нет доступных источников; проверьте назначение и права аккаунта")
        logger.info("[%s] слушает %d из %d источников", name, len(registered), len(sources))
        await client.run_until_disconnected()
    finally:
        await client.disconnect()


async def _run_account_guarded(name: str, *args) -> None:
    try:
        await _run_account(name, *args)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, CollectorError) else type(exc).__name__
        logger.error("[%s] аккаунт остановлен: %s", name, detail)
    else:
        logger.warning("[%s] Telegram отключился", name)


async def _run(accounts: dict, sources: dict, config: Config) -> None:
    headers = {"X-API-Key": config.ingest_api_key} if config.ingest_api_key else {}
    async with httpx.AsyncClient(timeout=20, headers=headers, trust_env=False) as http:
        delivery = Delivery(http, config)
        workers = [asyncio.create_task(delivery.worker()) for _ in range(WORKERS)]
        login_lock = asyncio.Lock()
        try:
            await asyncio.gather(*(_run_account_guarded(name, accounts[name], assigned, config, delivery, login_lock)
                                   for name, assigned in sources.items()))
        finally:
            await delivery.close(workers)
    raise CollectorError("ни один аккаунт не продолжает работу")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="проверить настройки без сетевых запросов")
    args = parser.parse_args()
    load_dotenv(BASE_DIR / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = _load_settings()
        accounts, sources = _load_configs(Path(os.environ.get("ACCOUNTS_FILE", BASE_DIR / "accounts.yml")),
                                          Path(os.environ.get("SOURCES_FILE", BASE_DIR / "sources.yml")))
        if config.allow_interactive_login and any(not accounts[name]["phone"] for name in sources):
            raise CollectorError("для ALLOW_INTERACTIVE_LOGIN=1 заполните phone у каждого назначенного аккаунта")
        if args.check_config:
            logger.info("Настройки корректны: %d активных аккаунтов, %d источников",
                        len(sources), sum(map(len, sources.values())))
            return 0
        asyncio.run(_run(accounts, sources, config))
    except CollectorError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
