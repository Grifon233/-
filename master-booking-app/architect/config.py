from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    architect_token: str = ""
    api_url: str = "http://localhost:8000"
    database_url: str = "sqlite+aiosqlite:///./master_booking.db"
    upload_dir: Path = Path("./uploads")
    proxy_url: Optional[str] = None
    admin_dangerous_commands_enabled: bool = False
    token_encryption_key: str = ""

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
