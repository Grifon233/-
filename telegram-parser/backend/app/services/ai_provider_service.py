from typing import Dict, List, Optional

from app.core.config import settings


PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "base_url": None,
        "key_setting": "OPENAI_API_KEY",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_setting": "OPENROUTER_API_KEY",
        "models": ["openrouter/auto", "meta-llama/llama-3-70b-instruct"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_setting": "DEEPSEEK_API_KEY",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
}


def get_provider_config(provider: str) -> Dict:
    config = PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unsupported AI provider: {provider}")
    return config


def get_provider_catalog() -> List[Dict]:
    return [
        {
            "id": provider_id,
            "name": config["name"],
            "models": config["models"],
            "configured": bool(getattr(settings, config["key_setting"], None)),
        }
        for provider_id, config in PROVIDERS.items()
    ]


def get_ai_client(provider: str, api_key: Optional[str] = None):
    from openai import AsyncOpenAI

    config = get_provider_config(provider)
    resolved_key = api_key or getattr(settings, config["key_setting"], None)
    if not resolved_key:
        raise ValueError(f"API key is not configured for provider: {provider}")
    kwargs = {"api_key": resolved_key}
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]
    return AsyncOpenAI(**kwargs)

