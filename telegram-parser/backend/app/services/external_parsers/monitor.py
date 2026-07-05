"""Adapter for telegram-channels-monitor (volom).

Upstream: https://github.com/volom/telegram-channels-monitor
A realtime poller: every ``time_pause`` seconds it pulls the last
``limit`` messages from each monitored channel and reports any whose
text contains one of the keywords (case-insensitive substring).

The keyword check is ported verbatim (``check_key_msg``). Instead of
forwarding hits to a Telegram bot, we record them into the run's CSV so
they land in the combine. The Telethon client is built from the combine
account (session reused via the bridge, proxy enforced).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from app.services.external_parsers.base import (
    int_config,
    normalize_channel_ref,
    split_config_list,
    telegram_message_link,
)

logger = logging.getLogger(__name__)


def check_key_msg(msg: str, kw: list[str]):
    """Ported verbatim from upstream ``run_monitoring.check_key_msg``.

    Returns ``(matched: bool, matched_keywords: str)``.
    """
    msg = msg.lower()
    msg = re.sub(r"\s+", " ", msg).strip(" ")
    hits = [s in msg for s in kw]
    from itertools import compress
    return any(hits), ", ".join(list(compress(kw, hits)))


async def run_monitor(client, config: dict, writer, stop_event) -> None:
    channels = [
        normalize_channel_ref(c)
        for c in split_config_list(config.get("channels"))
    ]
    channels = [c for c in channels if c != ""]
    key_words = [k.lower() for k in split_config_list(config.get("keywords"))]
    key_words = [re.sub(r"\s+", " ", k) for k in key_words]
    time_pause = int_config(config, "time_pause", 60, minimum=10, maximum=3600)
    limit_msg = int_config(config, "limit", 3, minimum=1, maximum=50)

    if not channels:
        raise ValueError("укажите хотя бы один канал для мониторинга")
    if not key_words:
        raise ValueError("укажите хотя бы одно ключевое слово")

    seen: set[tuple] = set()

    while not stop_event.is_set():
        for channel in channels:
            if stop_event.is_set():
                break
            try:
                async for message in client.iter_messages(channel, limit=limit_msg):
                    text = message.message or ""
                    if not text:
                        continue
                    key = (channel, message.id)
                    if key in seen:
                        continue
                    matched, matched_kw = check_key_msg(text, key_words)
                    if not matched:
                        continue
                    seen.add(key)

                    chat = await message.get_chat()
                    username = getattr(chat, "username", None)
                    link = telegram_message_link(
                        username,
                        getattr(chat, "id", ""),
                        message.id,
                    )
                    sender = await message.get_sender()
                    writer.write({
                        "matched_at": message.date.isoformat() if message.date else datetime.utcnow().isoformat(),
                        "channel": username or str(getattr(chat, "id", channel)),
                        "channel_title": getattr(chat, "title", "") or "",
                        "link": link,
                        "keyword": matched_kw,
                        "sender_id": getattr(sender, "id", "") or "",
                        "sender_username": getattr(sender, "username", "") or "",
                        "text": text[:500],
                    })
            except Exception as exc:  # noqa: BLE001
                logger.warning("monitor: channel %r failed: %s", channel, exc)
                continue

        # Interruptible sleep: wake immediately if a stop is requested.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=time_pause)
        except asyncio.TimeoutError:
            pass
