from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup


WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return WHITESPACE_RE.sub(" ", text).strip()


def html_to_text(value: object) -> str:
    if value is None:
        return ""
    raw = str(value)
    if "<" not in raw:
        return clean_text(raw)
    soup = BeautifulSoup(raw, "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_rss_datetime(value: str | None) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().isoformat(timespec="seconds")


def parse_russian_datetime(value: str | None) -> Optional[str]:
    if not value:
        return None
    value = clean_text(value)
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y %H:%M")
    except ValueError:
        return None
    return parsed.astimezone().isoformat(timespec="seconds")


def normalize_for_match(value: str) -> str:
    return clean_text(value).lower().replace("ё", "е")


def short_source_id(url: str, pattern: str) -> str:
    match = re.search(pattern, url)
    return match.group(1) if match else url
