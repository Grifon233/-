"""Failover-клиент для локального пула ключей разных LLM-провайдеров."""
import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    model: str


PROVIDERS = {
    "mistral": Provider("mistral", "https://api.mistral.ai/v1/chat/completions", "mistral-small-latest"),
    "cohere": Provider("cohere", "https://api.cohere.com/v2/chat", "command-a-03-2025"),
    "openrouter": Provider(
        "openrouter", "https://openrouter.ai/api/v1/chat/completions",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "cloudflare": Provider(
        "cloudflare",
        "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
        "@cf/qwen/qwen2.5-72b-instruct",
    ),
    "aihubmix": Provider("aihubmix", "https://aihubmix.com/v1/chat/completions", "gpt-4o-mini"),
}


class LLMRouter:
    def __init__(self) -> None:
        self._keys: dict[str, list[str]] = {}
        self._indices: dict[str, int] = {}
        self._cooldown: dict[tuple[str, str], float] = {}
        self._loaded_signature: tuple | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _order() -> list[str]:
        return list(dict.fromkeys(
            name for part in settings.llm_provider_order.split(",")
            if (name := part.strip().lower()) in PROVIDERS
            and (name != "cloudflare" or settings.llm_cloudflare_account_id)
        ))

    @property
    def configured(self) -> bool:
        self._load()
        return any(self._keys.get(name) for name in self._order())

    def _load(self) -> None:
        path = settings.llm_api_keys_file.strip()
        source = Path(path) if path else None
        try:
            stat = source.stat() if source is not None else None
        except OSError:
            stat = None
        signature = (path, None if stat is None else (stat.st_mtime_ns, stat.st_size))
        if signature == self._loaded_signature:
            return
        self._loaded_signature = signature
        self._keys = {name: [] for name in PROVIDERS}
        self._indices.clear()
        self._cooldown.clear()
        if source is None:
            return
        try:
            lines = source.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            logger.warning("Cannot read LLM API keys file (%s)", type(exc).__name__)
            return

        current: str | None = None
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.search(r" - ([\w\-.]+)\s*$", line)
            if match:
                if current and match.group(1) not in self._keys[current]:
                    self._keys[current].append(match.group(1))
                continue
            current = next((
                name for name in PROVIDERS
                if re.search(rf"(?<!\w){name}(?!\w)", line, re.IGNORECASE)
            ), None)
        logger.info(
            "Loaded LLM key pools: %s",
            {name: len(keys) for name, keys in self._keys.items()},
        )

    @staticmethod
    def _request(provider: Provider, key: str, messages: list[dict]) -> dict:
        headers = {"Authorization": f"Bearer {key}"}
        if provider.name == "cloudflare":
            url = provider.url.format(account_id=settings.llm_cloudflare_account_id, model=provider.model)
            return {"url": url, "headers": headers, "json": {"messages": messages}}
        payload = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": 250,
            "temperature": 0,
        }
        return {"url": provider.url, "headers": headers, "json": payload}

    @staticmethod
    def _content(provider: Provider, data: dict) -> str | None:
        if not isinstance(data, dict):
            return None
        if provider.name == "cloudflare":
            value = data.get("result")
            text = value.get("response") if isinstance(value, dict) else None
        elif provider.name == "cohere":
            value = data.get("message")
            parts = value.get("content") if isinstance(value, dict) else None
            text = "".join(
                part["text"] for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ) if isinstance(parts, list) else None
        else:
            choices = data.get("choices")
            value = choices[0] if isinstance(choices, list) and choices else None
            message = value.get("message") if isinstance(value, dict) else None
            text = message.get("content") if isinstance(message, dict) else None
        return text if isinstance(text, str) and text.strip() else None

    async def chat(
        self, messages: list[dict], validator: Callable[[str], bool] | None = None,
    ) -> str | None:
        self._load()
        async with self._lock:
            pools: list[tuple[Provider, list[str]]] = []
            for name in self._order():
                keys = self._keys.get(name, [])
                if not keys:
                    continue
                start = self._indices.get(name, 0) % len(keys)
                self._indices[name] = (start + 1) % len(keys)
                pools.append((PROVIDERS[name], keys[start:] + keys[:start]))

        # Чередуем провайдеров, чтобы большой пул одного сервиса не вытеснил резервных.
        candidates = [
            (provider, keys[i])
            for i in range(max((len(keys) for _, keys in pools), default=0))
            for provider, keys in pools if i < len(keys)
        ]
        if not candidates:
            return None

        attempts = 0
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            for provider, key in candidates:
                if attempts >= settings.llm_max_attempts:
                    break
                pair = (provider.name, key)
                if self._cooldown.get(pair, 0) > time.monotonic():
                    continue
                attempts += 1
                try:
                    response = await client.post(**self._request(provider, key, messages))
                    if response.status_code == 200:
                        content = self._content(provider, response.json())
                        if content and (validator is None or validator(content)):
                            return content

                    cooldown = 60
                    if response.status_code in {401, 403}:
                        cooldown = 3600
                    elif response.status_code == 402:
                        cooldown = 1800
                    elif response.status_code >= 500:
                        cooldown = 15
                    self._cooldown[pair] = time.monotonic() + cooldown
                    logger.warning(
                        "LLM provider %s returned unusable response (HTTP %s)",
                        provider.name, response.status_code,
                    )
                except (httpx.HTTPError, ValueError, RecursionError) as exc:
                    self._cooldown[pair] = time.monotonic() + 15
                    logger.warning("LLM provider %s failed (%s)", provider.name, type(exc).__name__)
        return None


llm_router = LLMRouter()
