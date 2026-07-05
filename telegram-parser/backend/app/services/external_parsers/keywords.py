"""Adapter for telegram-keywords-parser (minaton-ru).

Upstream: https://github.com/minaton-ru/telegram-keywords-parser
A one-shot scan: for each chat, walk recent history and keep messages
whose *words* include one of the keywords (whole-word match), limited to
the last ``days`` days.

Ported faithfully from ``telegram-keywords-parser.py`` with two
deliberate changes for integration:
  * the Pyrogram client comes from the combine account pool
    (``telegram_service``) instead of a file session built from
    ``config.ini``;
  * the upstream ``else: return`` on a text-less message (which aborts
    the *entire* scan at the first such message — an upstream bug) is
    replaced with ``continue`` so the scan keeps going.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re

from dateutil.relativedelta import relativedelta
from app.services.external_parsers.base import (
    int_config,
    normalize_channel_ref,
    split_config_list,
    telegram_message_link,
)

logger = logging.getLogger(__name__)

# Word-cleaning regex, verbatim from the upstream parser: keep latin,
# cyrillic (incl. ёїієґ), digits, underscore and hyphen; everything
# else becomes a separator.
_WORD_RE = re.compile(r"[^a-zа-яёїієґ0-9_-]")


async def run_keywords(account, config: dict, writer, stop_event) -> None:
    from app.services.telegram_service import telegram_service

    chats = [
        normalize_channel_ref(c)
        for c in split_config_list(config.get("channels"))
    ]
    chats = [c for c in chats if c != ""]
    keywords = [k.lower() for k in split_config_list(config.get("keywords"))]
    days = int_config(config, "days", 2, minimum=1, maximum=90)
    limit = int_config(config, "limit", 100, minimum=1, maximum=5000)

    if not chats:
        raise ValueError("укажите хотя бы один чат/канал")
    if not keywords:
        raise ValueError("укажите хотя бы одно ключевое слово")

    keyword_set = set(keywords)
    start_date = datetime.datetime.now() - relativedelta(days=days)

    client = await telegram_service.get_client(account)  # Pyrogram, proxy-guarded

    for chat in chats:
        if stop_event.is_set():
            break
        try:
            async for message in client.get_chat_history(chat, limit=limit):
                if stop_event.is_set():
                    break
                msg_date = getattr(message, "date", None)
                if msg_date is not None and msg_date < start_date:
                    # History is newest-first; once we pass the window we
                    # can stop scanning this chat.
                    break

                text = message.text or message.caption or ""
                if not text:
                    continue  # upstream had ``return`` here (a bug)

                words = _WORD_RE.sub(" ", text.lower()).split()
                matched = keyword_set.intersection(words)
                if not matched:
                    continue

                username = getattr(getattr(message, "chat", None), "username", None)
                link = telegram_message_link(
                    username,
                    getattr(message.chat, "id", ""),
                    message.id,
                )
                writer.write({
                    "matched_at": msg_date.isoformat() if msg_date else "",
                    "channel": username or str(getattr(message.chat, "id", chat)),
                    "channel_title": getattr(message.chat, "title", "") or "",
                    "link": link,
                    "keyword": ", ".join(sorted(matched)),
                    "sender_id": getattr(getattr(message, "from_user", None), "id", "") or "",
                    "sender_username": getattr(getattr(message, "from_user", None), "username", "") or "",
                    "text": text[:500],
                })
                await asyncio.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            # One bad chat (private/not found) should not kill the run.
            logger.warning("keywords parser: chat %r failed: %s", chat, exc)
            continue
