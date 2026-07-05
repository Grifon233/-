"""Failover-клиент для локального пула ключей разных LLM-провайдеров."""
import asyncio
import logging
import re
import time
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
    kind: str = "openai"


PROVIDERS = {
    "mistral": Provider(
        "mistral", "https://api.mistral.ai/v1/chat/completions",
        "mistral-small-latest",
    ),
    "cohere": Provider(
        "cohere", "https://api.cohere.com/v2/chat",
        "command-a-03-2025", "cohere",
    ),
    "openrouter": Provider(
        "openrouter", "https://openrouter.ai/api/v1/chat/completions",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "cloudflare": Provider(
        "cloudflare",
        "https://api.cloudflare.com/client/v4/accounts/"
        "18e987563108f245c732ad4f65497371/ai/run/"
        "@cf/qwen/qwen2.5-72b-instruct",
        "qwen2.5-72b-instruct", "cloudflare",
    ),
    "aihubmix": Provider(
        "aihubmix", "https://aihubmix.com/v1/chat/completions",
        "gpt-4o-mini",
    ),
}


class LLMRouter:
    def __init__(self) -> None:
        self._keys: dict[str, list[str]] = {}
        self._indices: dict[str, int] = {}
        self._cooldown: dict[tuple[str, str], float] = {}
        self._loaded_path = ""
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        self._load()
        return any(self._keys.values())

    def _load(self) -> None:
        path = settings.llm_api_keys_file.strip()
        if not path or path == self._loaded_path:
            return
        self._loaded_path = path
        self._keys = {name: [] for name in PROVIDERS}
        self._indices = {name: 0 for name in PROVIDERS}
        source = Path(path)
        if not source.is_file():
            logger.error("LLM API keys file not found: %s", source)
            return

        current: str | None = None
        for raw_line in source.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            lower = line.casefold()
            for name in PROVIDERS:
                if name in lower and " - " not in line:
                    current = name
                    break
            match = re.search(r" - ([\w\-.]+)", line)
            if match and current:
                self._keys[current].append(match.group(1))
        logger.info(
            "Loaded LLM key pools: %s",
            {name: len(keys) for name, keys in self._keys.items()},
        )

    def _request(self, provider: Provider, key: str, messages: list[dict]) -> dict:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if provider.kind == "cloudflare":
            return {"url": provider.url, "headers": headers, "json": {"messages": messages}}
        payload = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": 250,
            "temperature": 0,
        }
        return {"url": provider.url, "headers": headers, "json": payload}

    @staticmethod
    def _content(provider: Provider, data: dict) -> str | None:
        if provider.kind == "cloudflare":
            return data.get("result", {}).get("response")
        if provider.kind == "cohere":
            parts = data.get("message", {}).get("content", [])
            return parts[0].get("text") if parts else None
        return data.get("choices", [{}])[0].get("message", {}).get("content")

    async def chat(self, messages: list[dict]) -> str | None:
        self._load()
        order = [
            name.strip().lower()
            for name in settings.llm_provider_order.split(",")
            if name.strip().lower() in PROVIDERS
        ]
        attempts = 0
        async with self._lock:
            candidates: list[tuple[Provider, str]] = []
            now = time.monotonic()
            for name in order:
                keys = self._keys.get(name, [])
                if not keys:
                    continue
                start = self._indices.get(name, 0) % len(keys)
                for offset in range(len(keys)):
                    key = keys[(start + offset) % len(keys)]
                    if self._cooldown.get((name, key), 0) <= now:
                        candidates.append((PROVIDERS[name], key))
                self._indices[name] = (start + 1) % len(keys)

        async with httpx.AsyncClient(
            timeout=settings.llm_timeout,
            follow_redirects=True,
        ) as client:
            for provider, key in candidates:
                if attempts >= settings.llm_max_attempts:
                    break
                attempts += 1
                try:
                    response = await client.post(**self._request(provider, key, messages))
                    if response.status_code == 200:
                        content = self._content(provider, response.json())
                        if content:
                            logger.info("LLM extraction succeeded via %s", provider.name)
                            return content

                    cooldown = 60
                    if response.status_code in {401, 403}:
                        cooldown = 3600
                    elif response.status_code == 402:
                        cooldown = 1800
                    elif response.status_code >= 500:
                        cooldown = 15
                    self._cooldown[(provider.name, key)] = time.monotonic() + cooldown
                    logger.warning(
                        "LLM provider %s returned HTTP %s",
                        provider.name, response.status_code,
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    self._cooldown[(provider.name, key)] = time.monotonic() + 15
                    logger.exception("LLM provider %s failed", provider.name)
        return None


llm_router = LLMRouter()
