from typing import Any, Optional
from pydantic import field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Telegram Comb"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str
    ADMIN_API_TOKEN: str
    ENCRYPTION_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "tgcomb"
    POSTGRES_PORT: str = "5432"

    # SQLite for development (no Docker needed)
    USE_SQLITE: bool = True
    SQLITE_DB_PATH: str = "tgcomb.db"

    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        if isinstance(v, str) and v:
            return v

        # Use SQLite if USE_SQLITE is true
        if info.data.get("USE_SQLITE", True):
            db_path = info.data.get("SQLITE_DB_PATH", "tgcomb.db")
            return f"sqlite+aiosqlite:///{db_path}"

        # Otherwise use PostgreSQL
        from urllib.parse import quote_plus
        password = quote_plus(info.data.get('POSTGRES_PASSWORD', ''))
        user = info.data.get('POSTGRES_USER', '')
        server = info.data.get('POSTGRES_SERVER', '')
        port = info.data.get('POSTGRES_PORT', '')
        db = info.data.get('POSTGRES_DB', '')
        return f"postgresql+asyncpg://{user}:{password}@{server}:{port}/{db}"

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        from cryptography.fernet import Fernet
        try:
            Fernet(v.encode())
        except Exception as exc:
            raise ValueError(f"Invalid ENCRYPTION_KEY format (must be 32-byte url-safe base64): {exc}")
        return v

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str

    OPENAI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None

    # Public Telegram Desktop app credentials used only for tdata to
    # Pyrogram StringSession conversion when the operator does not
    # provide their own my.telegram.org app credentials.
    TELEGRAM_API_ID: int = 2040
    TELEGRAM_API_HASH: str = "b18441a1ff607e10a989891a5462e627"

    # proxy6.net — primary proxy vendor. The legacy ``WEBSHARE_API_KEY``
    # name is honored for back-compat (it was the original label
    # before we discovered the key belongs to proxy6.net, not
    # webshare.io).
    PROXY6_API_KEY: Optional[str] = None
    WEBSHARE_API_KEY: Optional[str] = None

    # TGStat (https://api.tgstat.ru) — external catalog of 2.7M+
    # Telegram channels. Used by the ``tgstat_search`` parser type
    # as a no-Telegram-account-required alternative to ``chat_search``.
    # Register at https://tgstat.ru/my/profile and pick the
    # ``API Stat / API Search`` plan (S or above) to enable
    # ``channels/search``. The free tier only works for channels
    # you own.
    TGSTAT_API_TOKEN: Optional[str] = None
    TGSTAT_API_BASE: str = "https://api.tgstat.ru"

    # SMSFAST (https://smsfast.cc) — virtual-number / SMS-activation
    # service used to auto-register fresh Telegram accounts. Standard
    # SMS-Activate-compatible ``handler_api.php`` protocol. Register at
    # https://smsfast.cc and copy the API key from account settings.
    SMSFAST_API_TOKEN: Optional[str] = None
    SMSFAST_API_BASE: str = "https://smsfastapi.com/stubs/handler_api.php"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore"
    )

settings = Settings()
