"""Настройки backend. Всё берётся из переменных окружения / .env."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sighting_ttl: int = 7200
    store_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    ingest_api_key: str = ""

    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_keys_file: str = ""
    llm_provider_order: str = "mistral,cohere,openrouter,cloudflare,aihubmix"
    llm_timeout: float = 30.0
    llm_max_attempts: int = 8

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocoding_user_agent: str = "couriers-map/0.3"

    valhalla_url: str = ""

    feedback_bot_token: str = ""
    feedback_chat_id: str = "623597334"
    feedback_rate_limit: int = 5

    @field_validator("sighting_ttl")
    @classmethod
    def validate_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("SIGHTING_TTL must be greater than zero")
        return value

    @field_validator("store_backend")
    @classmethod
    def validate_store_backend(cls, value: str) -> str:
        value = value.strip().lower()
        if value != "memory":
            raise ValueError(
                "Only STORE_BACKEND=memory is implemented; Redis persistence is not ready"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
