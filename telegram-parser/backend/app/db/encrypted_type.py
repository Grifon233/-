"""Transparent encryption for sensitive database columns."""

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

from app.core.config import settings


class EncryptedString(TypeDecorator):
    """Encrypt new values and keep legacy plaintext readable during migration."""

    impl = Text
    cache_ok = True

    @staticmethod
    def _fernet() -> Fernet:
        return Fernet(settings.ENCRYPTION_KEY.encode())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        raw = str(value)
        try:
            self._fernet().decrypt(raw.encode())
            return raw
        except (InvalidToken, ValueError):
            return self._fernet().encrypt(raw.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self._fernet().decrypt(str(value).encode()).decode()
        except (InvalidToken, ValueError):
            return value
