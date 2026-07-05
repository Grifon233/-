"""
Утилиты для безопасного хранения токенов ботов.
Шифрование at rest через Fernet (cryptography).
Если ключ не задан — работаем с открытым текстом.
"""
import base64
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

# Кешируем cipher, чтобы не парсить ключ каждый раз
_cipher = None


def _get_cipher():
    global _cipher
    if _cipher is not None:
        return _cipher

    raw_key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        _cipher = None
        return None

    # Если ключ не 32 байта url-safe base64 — пробуем через SHA-256
    try:
        from cryptography.fernet import Fernet
        # Проверяем валидность ключа
        try:
            key_bytes = raw_key.encode("utf-8")
            base64.urlsafe_b64decode(key_bytes)  # Проверка формата
            _cipher = Fernet(raw_key)
        except (ValueError, base64.binascii.Error):
            # Невалидный Fernet ключ — хешируем
            derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode()).digest())
            _cipher = Fernet(derived.decode())
    except ImportError:
        logger.warning("cryptography not installed — tokens stored as plain text")
        _cipher = None

    return _cipher


def encrypt_token(plain: str) -> str:
    """Зашифровать токен. Если ключ не задан — вернуть как есть."""
    if not plain:
        return plain
    c = _get_cipher()
    if c is None:
        return plain
    try:
        return c.encrypt(plain.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Token encryption failed: {e}")
        return plain


def decrypt_token(encrypted: str) -> str:
    """Расшифровать токен. Если ключ не задан — вернуть как есть."""
    if not encrypted:
        return encrypted
    c = _get_cipher()
    if c is None:
        return encrypted
    try:
        return c.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Token decryption failed: {e}")
        return encrypted


def mask_token(token: str | None) -> str | None:
    """Маскировать токен для логов — показать первые 6 и последние 4 символа."""
    if not token:
        return None
    if len(token) <= 12:
        return token[:4] + "****"
    return token[:6] + "****" + token[-4:]
