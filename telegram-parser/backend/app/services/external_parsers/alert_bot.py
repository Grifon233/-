"""Adapter for keyword_alert_bot (crazypeace).

Upstream: https://github.com/crazypeace/keyword_alert_bot
A realtime, event-driven alerter. Its distinctive features over the
other two parsers are (a) JS-style **regex** keywords (``/pattern/i``)
and (b) **dedup** so the same hit isn't reported twice. Both are ported
faithfully here:
  * ``js_to_py_re`` and ``is_regex_str`` are copied verbatim from
    ``main.py``;
  * dedup uses ``diskcache`` with a short expiry, exactly like upstream.

Instead of the upstream's own SQLite subscription store + outbound bot,
the monitored channels and keywords come from the run config and hits
are written into the combine run CSV.
"""
from __future__ import annotations

import asyncio
import logging
import re as regex
from datetime import datetime
from tempfile import TemporaryDirectory

from app.services.external_parsers.base import (
    int_config,
    normalize_channel_ref,
    peer_id_candidates,
    split_config_list,
    telegram_message_link,
)

logger = logging.getLogger(__name__)


def js_to_py_re(rx):
    """Verbatim from upstream ``main.js_to_py_re`` — parse ``/pat/flags``.

    Only the ``i`` and ``g`` flags are supported.
    """
    query, params = rx[1:].rsplit("/", 1)
    if "g" in params:
        obj = regex.findall
    else:
        obj = regex.search
    return lambda L: obj(query, L, flags=regex.I if "i" in params else 0)


def is_regex_str(string):
    """Verbatim from upstream ``main.is_regex_str``."""
    return regex.search(r"^/.*/[a-zA-Z]*?$", string)


def _match_keyword(keyword: str, text: str):
    """Return the matched substring(s) for a keyword, or None.

    Mirrors upstream: a ``/regex/flags`` keyword runs as a regex, any
    other keyword is a plain substring test.
    """
    if is_regex_str(keyword):
        result = js_to_py_re(keyword)(text)
        if result is None:
            return None
        if isinstance(result, regex.Match):
            return [result.group()]
        matches = []
        for item in result:
            item = "".join(item) if isinstance(item, tuple) else item
            if item:
                matches.append(item)
        matches = list(set(matches))
        return matches or None
    else:
        return [keyword] if keyword in text else None


def _normalize_channel(value: str) -> str:
    normalized = normalize_channel_ref(value)
    if isinstance(normalized, int):
        return str(normalized)
    return normalized.lower()


def _validate_keyword(keyword: str) -> None:
    if not is_regex_str(keyword):
        return
    try:
        js_to_py_re(keyword)("")
    except regex.error as exc:
        raise ValueError(f"некорректное регулярное выражение {keyword!r}: {exc}") from exc


async def run_alert_bot(client, config: dict, writer, stop_event) -> None:
    from telethon import events

    channels = split_config_list(config.get("channels"))
    keywords = split_config_list(
        config.get("keywords"),
        preserve_regex_commas=True,
    )
    if not keywords:
        raise ValueError("укажите хотя бы одно ключевое слово (или /regex/)")
    for keyword in keywords:
        _validate_keyword(keyword)

    # Normalized username set + numeric id set for channel filtering.
    want_usernames = set()
    want_ids = set()
    for ch in channels:
        norm = normalize_channel_ref(ch)
        if isinstance(norm, int):
            want_ids.update(peer_id_candidates(norm))
        elif norm:
            want_usernames.add(norm.lower())

    import diskcache
    cache_dir = TemporaryDirectory(prefix="alert_bot_")
    cache = diskcache.Cache(cache_dir.name)
    dedup_expire = int_config(
        config, "dedup_expire", 5, minimum=1, maximum=86400
    )

    async def _handler(event):
        try:
            text = event.message.message or ""
            if event.message.file and getattr(event.message.file, "name", None):
                text += " {}".format(event.message.file.name)
            if not text:
                return

            chat = await event.get_chat()
            username = (getattr(chat, "username", None) or "").lower()
            chat_id = getattr(chat, "id", None)
            id_candidates = set()
            id_candidates.update(peer_id_candidates(chat_id))
            id_candidates.update(peer_id_candidates(getattr(event, "chat_id", None)))
            if want_usernames or want_ids:
                if username not in want_usernames and not (id_candidates & want_ids):
                    return

            for keyword in keywords:
                matched = _match_keyword(keyword, text)
                if not matched:
                    continue
                dedup_key = f"{chat_id}_{event.message.id}_{keyword}"
                if not cache.add(dedup_key, 1, expire=dedup_expire):
                    continue  # already reported recently
                link = telegram_message_link(
                    username,
                    chat_id or getattr(event, "chat_id", ""),
                    event.message.id,
                )
                sender = await event.get_sender()
                writer.write({
                    "matched_at": event.message.date.isoformat() if event.message.date else datetime.utcnow().isoformat(),
                    "channel": username or str(chat_id),
                    "channel_title": getattr(chat, "title", "") or "",
                    "link": link,
                    "keyword": ", ".join(str(m) for m in matched),
                    "sender_id": getattr(sender, "id", "") or "",
                    "sender_username": getattr(sender, "username", "") or "",
                    "text": text[:500],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert_bot handler error: %s", exc)

    client.add_event_handler(_handler, events.NewMessage())
    client.add_event_handler(_handler, events.MessageEdited())
    try:
        await stop_event.wait()
    finally:
        client.remove_event_handler(_handler)
        cache.close()
        cache_dir.cleanup()
