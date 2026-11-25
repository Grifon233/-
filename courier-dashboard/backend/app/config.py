"""Настройки backend. Всё берётся из переменных окружения / .env."""
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    sighting_ttl: int = Field(default=7200, gt=0)
    sighting_max_future_skew: int = Field(default=300, ge=0)
    store_backend: str = "memory"
    sightings_db_path: str = ""
    ingest_api_key: str = ""
    ingest_allow_unauthenticated: bool = False
    cors_origins: str = ""

    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_keys_file: str = ""
    llm_provider_order: str = "mistral,cohere,openrouter,cloudflare,aihubmix"
    llm_cloudflare_account_id: str = Field(default="", pattern=r"^(?:[a-fA-F0-9]{32})?$")
    llm_timeout: float = Field(default=8.0, gt=0, allow_inf_nan=False)
    llm_max_attempts: int = Field(default=8, gt=0)
    llm_allow_private_text: bool = False

    nominatim_url: str = ""
    geocoding_user_agent: str = "couriers-map/0.3"
    geocoding_timeout: float = Field(default=7.0, gt=0, allow_inf_nan=False)

    valhalla_url: str = ""

    feedback_bot_token: str = Field(default="", pattern=r"^(?:[0-9]+:[A-Za-z0-9_-]+)?$")
    feedback_chat_id: str = ""
    feedback_rate_limit: int = Field(default=5, gt=0)
    feedback_global_rate_limit: int = Field(default=30, gt=0)

    @field_validator(
        "ingest_api_key", "feedback_chat_id", "sightings_db_path",
        "feedback_bot_token", "llm_cloudflare_account_id", mode="before",
    )
    @classmethod
    def strip_secret_whitespace(cls, value: str) -> str:
        return value.strip()

    @field_validator("store_backend")
    @classmethod
    def validate_store_backend(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"memory", "sqlite"}:
            raise ValueError("STORE_BACKEND must be memory or sqlite")
        return value

    @field_validator("nominatim_url", "valhalla_url")
    @classmethod
    def validate_service_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlsplit(value)
        _ = parsed.port
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(char.isspace() for char in value)
        ):
            raise ValueError("service URL must be an HTTP(S) base URL without credentials")
        return value

    @model_validator(mode="after")
    def validate_storage(self) -> "Settings":
        if self.store_backend == "sqlite" and self.sightings_db_path in {"", ":memory:"}:
            raise ValueError("SIGHTINGS_DB_PATH must be set when STORE_BACKEND=sqlite")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
