"""Shared infrastructure for the external-parser adapters.

Provides:
* an in-process run registry (start/stop realtime parsers like the
  ``spambot_runner`` pattern, but keyed by ``run_id``);
* a Telethon client builder that reuses a combine account's session
  (via the Pyrogram→Telethon bridge) and its bound proxy — the proxy
  guard is enforced exactly like :mod:`app.services.telegram_service`;
* helpers to persist run status and append matched rows to a CSV.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Columns written to every parser's results CSV. Keeping them uniform
# lets the results endpoint and a future contact-import treat all three
# parsers the same way.
RESULT_FIELDS = [
    "matched_at",
    "channel",
    "channel_title",
    "link",
    "keyword",
    "sender_id",
    "sender_username",
    "text",
]

EXPORT_DIR = "exports/external_parsers"


# ---------------------------------------------------------------------------
# Config / Telegram identifier helpers
# ---------------------------------------------------------------------------
def split_config_list(value: Any, *, preserve_regex_commas: bool = False) -> list[str]:
    """Normalize UI/API list-ish config values into a clean string list.

    The frontend sends arrays, but API callers sometimes send textarea
    strings. We accept both. Commas are convenient separators, except inside
    alert-bot JS-style regex keywords such as ``/foo,bar/i``.
    """
    if value is None:
        return []
    if isinstance(value, str):
        chunks = _split_textarea_list(value, preserve_regex_commas=preserve_regex_commas)
        return [item.strip() for item in chunks if item.strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _split_textarea_list(raw: str, *, preserve_regex_commas: bool = False) -> list[str]:
    if not preserve_regex_commas:
        return re.split(r"[\n,]", raw)

    parts: list[str] = []
    buf: list[str] = []
    in_regex = False
    escaped = False
    at_item_start = True

    for ch in raw:
        if ch in "\r\n":
            parts.append("".join(buf))
            buf = []
            in_regex = False
            escaped = False
            at_item_start = True
            continue

        if ch == "," and not in_regex:
            parts.append("".join(buf))
            buf = []
            escaped = False
            at_item_start = True
            continue

        if ch == "/" and preserve_regex_commas:
            if in_regex and not escaped:
                in_regex = False
            elif at_item_start:
                in_regex = True

        buf.append(ch)
        if not ch.isspace():
            at_item_start = False
        escaped = (ch == "\\" and not escaped)
        if ch != "\\":
            escaped = False

    parts.append("".join(buf))
    return parts


def int_config(config: dict, key: str, default: int, *,
               minimum: int, maximum: int) -> int:
    """Read an integer config value and clamp it to an operational range."""
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def normalize_channel_ref(value: Any) -> str | int:
    """Normalize a Telegram chat/channel reference from UI input.

    Accepts ``@name``, ``name``, ``https://t.me/name`` and
    ``https://t.me/c/<internal_id>/...``. Public references become plain
    usernames; private ``/c/`` links become marked IDs (``-100...``), which
    Pyrogram and Telethon can resolve when the account is already a member.
    """
    text = str(value).strip()
    if not text:
        return ""

    if re.match(r"^(?:https?://)?t\.me/", text, flags=re.I):
        url_text = text if "://" in text else f"https://{text}"
        parsed = urlparse(url_text)
        text = parsed.path.strip("/")
    else:
        text = text.strip("/")

    text = text.lstrip("@").strip()
    if not text:
        return ""

    # Message links to private channels are shaped like /c/123456/789.
    match = re.match(r"^c/(\d+)(?:/.*)?$", text, flags=re.I)
    if match:
        return int(f"-100{match.group(1)}")

    # Public message links are shaped like /username/789; keep username.
    if "/" in text and not text.startswith("+"):
        text = text.split("/", 1)[0]

    if text.lstrip("-").isdigit():
        return int(text)
    return text


def peer_id_candidates(value: Any) -> set[int]:
    """Return equivalent Telethon/Pyrogram IDs for a channel/group id."""
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return set()

    ids = {numeric}
    abs_text = str(abs(numeric))
    if numeric < 0 and abs_text.startswith("100") and len(abs_text) > 3:
        ids.add(int(abs_text[3:]))
    elif numeric > 0:
        ids.add(int(f"-100{numeric}"))
    return ids


def telegram_message_link(username: Optional[str], chat_id: Any, message_id: Any) -> str:
    """Build a public t.me link when possible, including private /c links."""
    if username:
        return f"https://t.me/{username}/{message_id}"

    try:
        numeric = int(chat_id)
    except (TypeError, ValueError):
        return ""

    internal = numeric
    abs_text = str(abs(numeric))
    if numeric < 0 and abs_text.startswith("100") and len(abs_text) > 3:
        internal = int(abs_text[3:])
    elif numeric < 0:
        internal = abs(numeric)
    return f"https://t.me/c/{internal}/{message_id}"


# ---------------------------------------------------------------------------
# In-process run registry
# ---------------------------------------------------------------------------
@dataclass
class RunHandle:
    run_id: int
    task: Optional[asyncio.Task] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    client: Any = None  # the connected Telethon/Pyrogram client, if any


_runs: dict[int, RunHandle] = {}


def get_handle(run_id: int) -> Optional[RunHandle]:
    return _runs.get(run_id)


def register(run_id: int) -> RunHandle:
    handle = RunHandle(run_id=run_id)
    _runs[run_id] = handle
    return handle


def unregister(run_id: int) -> None:
    _runs.pop(run_id, None)


def is_running(run_id: int) -> bool:
    handle = _runs.get(run_id)
    return bool(handle and handle.task and not handle.task.done())


async def request_stop(run_id: int) -> bool:
    """Signal a realtime run to stop and wait briefly for it to wind down."""
    handle = _runs.get(run_id)
    if not handle:
        return False
    handle.stop_event.set()
    if handle.task:
        try:
            await asyncio.wait_for(asyncio.shield(handle.task), timeout=15)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            handle.task.cancel()
        except Exception:  # noqa: BLE001
            pass
    return True


# ---------------------------------------------------------------------------
# Account / client helpers
# ---------------------------------------------------------------------------
async def load_account_with_proxy(db, account_id: int, project_id: int):
    """Load an account (with its proxy eagerly) scoped to the project."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.account import Account

    result = await db.execute(
        select(Account)
        .options(selectinload(Account.proxy))
        .where(Account.id == account_id, Account.project_id == project_id)
    )
    return result.scalar_one_or_none()


def telethon_proxy_tuple(proxy) -> Optional[tuple]:
    """Build a PySocks-style proxy tuple for Telethon from a Proxy row.

    Mirrors the proxy handling the upstream ``keyword_alert_bot`` uses
    (``(socks.<TYPE>, address, port)``) but adds auth when present.
    """
    if not proxy:
        return None
    import socks

    scheme = (proxy.scheme or "socks5").lower()
    proxy_type = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }.get(scheme, socks.SOCKS5)

    if proxy.username:
        return (proxy_type, proxy.host, int(proxy.port), True,
                proxy.username, proxy.password or "")
    return (proxy_type, proxy.host, int(proxy.port))


async def build_telethon_client(account):
    """Create (not connect) a Telethon client for a combine account.

    The account's Pyrogram session is converted to a Telethon
    ``StringSession`` so the same authorization is reused without a new
    login. The bound proxy is mandatory — we never connect bare.
    """
    from app.services.account_service import ProxyRequiredError, assert_proxy_bound
    from app.services.session_bridge import pyrogram_to_telethon_string

    assert_proxy_bound(account)
    if account.proxy is not None and getattr(account.proxy, "is_active", True) is False:
        raise ProxyRequiredError(
            f"Proxy for account {account.phone_number} is inactive/dead; refusing to connect."
        )
    if not account.session_string:
        raise ValueError("account has no session_string (not authorized)")

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    telethon_string = pyrogram_to_telethon_string(account.session_string)
    client = TelegramClient(
        StringSession(telethon_string),
        account.api_id,
        account.api_hash,
        proxy=telethon_proxy_tuple(account.proxy),
    )
    return client


# ---------------------------------------------------------------------------
# Status + results persistence
# ---------------------------------------------------------------------------
async def set_status(run_id: int, status, *, started: bool = False,
                     finished: bool = False, last_error: Optional[str] = None,
                     result_count: Optional[int] = None,
                     file_path: Optional[str] = None,
                     workdir: Optional[str] = None) -> None:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.external_parser import ExternalParserRun

    async with SessionLocal() as db:
        run = (
            await db.execute(
                select(ExternalParserRun).where(ExternalParserRun.id == run_id)
            )
        ).scalar_one_or_none()
        if not run:
            return
        run.status = status
        if started:
            run.started_at = datetime.utcnow()
        if finished:
            run.finished_at = datetime.utcnow()
        if last_error is not None:
            run.last_error = last_error[:1000]
        if result_count is not None:
            run.result_count = result_count
        if file_path is not None:
            run.file_path = file_path
        if workdir is not None:
            run.workdir = workdir
        await db.commit()


def results_csv_path(run_id: int) -> str:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    return os.path.abspath(os.path.join(EXPORT_DIR, f"run_{run_id}.csv"))


class ResultWriter:
    """Append matched rows to a per-run CSV, creating the header once."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self.path = results_csv_path(run_id)
        self.count = 0
        self._fh = None
        self._writer = None

    def _ensure_open(self):
        if self._fh is None:
            new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
            self._fh = open(self.path, "a", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fh, fieldnames=RESULT_FIELDS,
                                          extrasaction="ignore")
            if new:
                self._writer.writeheader()

    def write(self, row: dict) -> None:
        self._ensure_open()
        full = {k: row.get(k, "") for k in RESULT_FIELDS}
        self._writer.writerow(full)
        self._fh.flush()
        self.count += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
