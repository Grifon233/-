from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Iterable, Mapping, Sequence


Params = Mapping[str, object] | Sequence[tuple[str, object]] | None


def build_url(url: str, params: Params = None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode(params, doseq=True)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def fetch_bytes(url: str, config: dict, params: Params = None) -> bytes:
    full_url = build_url(url, params)
    request = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": config["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=int(config["request_timeout_seconds"]),
    ) as response:
        return response.read()


def fetch_text(url: str, config: dict, params: Params = None) -> str:
    return fetch_bytes(url, config, params).decode("utf-8", errors="ignore")

