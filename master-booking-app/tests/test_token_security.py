"""
Тесты безопасности токенов:
- Шифрование/расшифровка roundtrip
- Маскирование в логах
- Токен не возвращается в API
- set_webhook_for_bot не падает с NameError
- Логи не содержат raw token
"""
import logging
import os
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.token_utils import encrypt_token, decrypt_token, mask_token
from backend.config import get_webhook_url


def test_get_webhook_url_uses_api_path_by_default():
    """Новые боты должны ставить webhook на /api/webhook, который проксируется в backend."""
    import backend.config as config

    config.get_urls.cache_clear()
    with patch.dict(os.environ, {"WEB_URL": "https://example.test"}, clear=True):
        config.get_urls.cache_clear()
        assert get_webhook_url("TOKEN") == "https://example.test/api/webhook/TOKEN"
    config.get_urls.cache_clear()


def test_fastapi_accepts_new_and_legacy_webhook_paths():
    """Backend принимает новый /api/webhook и старый /webhook для уже созданных ботов."""
    from backend.main import app

    webhook_paths = {r.path for r in app.routes if "webhook" in r.path}
    assert "/api/webhook/{bot_token}" in webhook_paths
    assert "/webhook/{bot_token}" in webhook_paths


# ─── mask_token ─────────────────────────────────────────────────────────────────


class TestMaskToken:
    def test_mask_full_token(self):
        masked = mask_token("123456:AbcdefghIJKlmnoP")
        assert len(masked) == 14  # 6 + **** + 4
        assert "Abcdef" not in masked.split("****")[1]
        assert masked.endswith("noP")

    def test_mask_short_token(self):
        masked = mask_token("short")
        assert masked == "shor****"

    def test_mask_none(self):
        assert mask_token(None) is None

    def test_mask_empty(self):
        assert mask_token("") is None


# ─── encrypt / decrypt roundtrip ────────────────────────────────────────────────


class TestEncryptRoundtrip:
    FAKE_KEY = "dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBmZXJuZXQhISE="

    def _reset_cipher(self):
        import backend.token_utils
        backend.token_utils._cipher = None

    def test_plaintext_when_no_key(self):
        """Без ключа encrypt/decrypt — no-op."""
        self._reset_cipher()
        with patch.dict(os.environ, {}, clear=True):
            self._reset_cipher()
            token = "123456:ABC"
            assert encrypt_token(token) == token
            assert decrypt_token(token) == token

    def test_roundtrip_with_key(self):
        """С ключом encrypt → decrypt даёт исходный токен."""
        self._reset_cipher()
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": self.FAKE_KEY}, clear=True):
            self._reset_cipher()
            token = "123456:ABCdefGHIjklMNO"
            encrypted = encrypt_token(token)
            assert encrypted != token
            assert decrypt_token(encrypted) == token

    def test_different_tokens_different_ciphertext(self):
        """Одинаковые токены дают разный ciphertext (Fernet salt)."""
        self._reset_cipher()
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": self.FAKE_KEY}, clear=True):
            self._reset_cipher()
            token = "same_token_123"
            e1 = encrypt_token(token)
            e2 = encrypt_token(token)
            assert e1 != e2
            assert decrypt_token(e1) == token
            assert decrypt_token(e2) == token

    def test_decrypt_fails_with_wrong_key(self):
        """Расшифровка чужим ключом возвращает зашифрованный текст (graceful)."""
        self._reset_cipher()
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": self.FAKE_KEY}, clear=True):
            self._reset_cipher()
            encrypted = encrypt_token("secret_token_456")

        wrong_key = "d2Ryb25nIGtleSBmb3IgdGVzdGluZyBwdXJwb3Nlcw=="
        with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": wrong_key}, clear=True):
            self._reset_cipher()
            result = decrypt_token(encrypted)
            assert result == encrypted  # не расшифровался, вернул как есть

    def test_encrypt_empty(self):
        assert encrypt_token("") == ""

    def test_encrypt_none(self):
        assert encrypt_token(None) is None


# ─── API не возвращает токен ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_superadmin_api_does_not_return_token(db_session):
    """
    Супер-админ API /api/superadmin/masters не должен возвращать
    поле token у MasterBot.
    """
    from backend.database import Master, MasterBot

    master = Master(
        telegram_id=999888777,
        name="Test Master",
        is_demo=False,
    )
    db_session.add(master)
    await db_session.flush()

    bot = MasterBot(
        master_telegram_id=999888777,
        token="test_token_123",
        username="test_bot",
        status="running",
    )
    db_session.add(bot)
    await db_session.commit()

    import time
    from urllib.parse import urlencode
    from backend.middleware.tg_auth import sign_auth_params

    auth_ts = int(time.time())
    params = urlencode({
        "user": "623597334",
        "auth_ts": auth_ts,
        "sig": sign_auth_params(623597334, auth_ts),
    })

    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.database import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        response = test_client.get(f"/api/superadmin/masters?{params}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    masters = data.get("masters", [])
    for m in masters:
        bot_info = m.get("bot")
        if bot_info:
            assert "token" not in bot_info, f"Token leaked in API response: {bot_info}"


# ─── set_webhook_for_bot — нет NameError, нет утечки raw token ─────────────────


class TestBotManagerWebhook:
    """Проверяем что set_webhook_for_bot не падает и не логирует raw token."""

    @pytest.mark.asyncio
    async def test_set_webhook_no_nameerror(self):
        """set_webhook_for_bot с замоканным Bot не вызывает NameError."""
        from architect.services.bot_manager import bot_manager

        with patch("aiogram.Bot") as mock_bot_cls:
            mock_bot_instance = MagicMock()
            mock_bot_instance.delete_webhook = AsyncMock(return_value=True)
            mock_bot_instance.session.close = AsyncMock()
            mock_bot_cls.return_value = mock_bot_instance

            # Должно отработать без NameError
            result = await bot_manager.set_webhook_for_bot("123456:real_raw_token_abc")

            assert result is True
            mock_bot_instance.delete_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_webhook_log_does_not_contain_raw_token(self):
        """Лог set_webhook_for_bot не содержит raw token."""
        from architect.services.bot_manager import bot_manager

        logger = logging.getLogger("architect.services.bot_manager")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        raw = "123456:TOP_SECRET_RAW_TOKEN_TEST"

        with patch("aiogram.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot.delete_webhook = AsyncMock(return_value=True)
            mock_bot.session.close = AsyncMock()
            mock_bot_cls.return_value = mock_bot

            await bot_manager.set_webhook_for_bot(raw)

        logger.removeHandler(handler)
        handler.close()
        log_output = stream.getvalue()

        assert raw not in log_output, f"Raw token leaked in log: {log_output}"
        assert mask_token(raw) in log_output

    @pytest.mark.asyncio
    async def test_set_webhook_error_log_does_not_contain_raw_token(self):
        """Лог ошибки set_webhook_for_bot не содержит raw token."""
        from architect.services.bot_manager import bot_manager

        logger = logging.getLogger("architect.services.bot_manager")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)

        raw = "123456:RAW_TOKEN_FOR_ERROR_TEST"

        with patch("aiogram.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot.delete_webhook = AsyncMock(side_effect=Exception("API fail"))
            mock_bot.session.close = AsyncMock()
            mock_bot_cls.return_value = mock_bot

            await bot_manager.set_webhook_for_bot(raw)

        logger.removeHandler(handler)
        handler.close()
        log_output = stream.getvalue()

        assert raw not in log_output, f"Raw token leaked in error log: {log_output}"
        assert mask_token(raw) in log_output

    @pytest.mark.asyncio
    async def test_configure_webhook_returns_telegram_error_details(self):
        """Новый setup возвращает причину ошибки Telegram, а не просто False."""
        from architect.services.bot_manager import bot_manager

        raw = "123456:RAW_TOKEN_FOR_DETAIL_TEST"

        with patch("aiogram.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot.delete_webhook = AsyncMock(side_effect=Exception("Bad Request: bad webhook"))
            mock_bot.session.close = AsyncMock()
            mock_bot_cls.return_value = mock_bot

            ok, error = await bot_manager.configure_webhook_for_bot(raw)

        assert ok is False
        assert "bad webhook" in error
        mock_bot.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_configure_webhook_removes_saved_url_for_polling(self):
        """Перед polling снимаем старый webhook без удаления очереди обновлений."""
        from architect.services.bot_manager import bot_manager

        raw = "123456:RAW_TOKEN_FOR_INFO_TEST"

        with patch("aiogram.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot.delete_webhook = AsyncMock(return_value=True)
            mock_bot.session.close = AsyncMock()
            mock_bot_cls.return_value = mock_bot

            ok, error = await bot_manager.configure_webhook_for_bot(raw)

        assert ok is True
        assert error is None
        mock_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False, request_timeout=20)

    @pytest.mark.asyncio
    async def test_validate_token_uses_httpx_proxy_parameter(self):
        """HTTPX должен получать proxy=..., а не старый proxies=..."""
        import architect.services.bot_manager as bm_mod

        class FakeResponse:
            def json(self):
                return {"ok": True, "result": {"username": "created_bot"}}

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                assert kwargs["proxy"] == "http://proxy.example:8080"
                assert "proxies" not in kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                return FakeResponse()

        with patch.object(bm_mod.settings, "proxy_url", "http://proxy.example:8080"):
            with patch.object(bm_mod.httpx, "AsyncClient", FakeAsyncClient):
                valid, username = await bm_mod.bot_manager.validate_token("123456:RAW")

        assert valid is True
        assert username == "created_bot"

    @pytest.mark.asyncio
    async def test_delete_bot_removes_row_and_deletes_webhook(self, db_session):
        """Удаление бота снимает webhook и удаляет только MasterBot."""
        import architect.services.bot_manager as bm_mod
        from backend.database import MasterBot
        from tests.conftest import test_async_session_maker

        bot = MasterBot(
            master_telegram_id=777001,
            token="123456:RAW_DELETE_TOKEN_TEST",
            username="delete_me_bot",
            status="running",
        )
        db_session.add(bot)
        await db_session.commit()

        with patch.object(bm_mod, "async_session_maker", test_async_session_maker):
            with patch("aiogram.Bot") as mock_bot_cls:
                mock_bot = MagicMock()
                mock_bot.delete_webhook = AsyncMock()
                mock_bot.session.close = AsyncMock()
                mock_bot_cls.return_value = mock_bot

                deleted = await bm_mod.bot_manager.delete_bot(777001)

        assert deleted is True
        mock_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)

        async with test_async_session_maker() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(MasterBot).where(
                    MasterBot.master_telegram_id == 777001
                )
            )
            assert result.scalar_one_or_none() is None


# ─── configure_webhook_for_bot — нет утечки raw token в лог ────────────────────


class TestConfigureWebhook:
    """Проверяем что configure_webhook_for_bot не логирует raw token."""

    @pytest.mark.asyncio
    async def test_log_does_not_contain_raw_token(self):
        """Лог configure_webhook_for_bot не содержит raw token."""
        from backend.webhook import configure_webhook_for_bot

        logger = logging.getLogger("backend.webhook")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        raw = "123456:ANOTHER_RAW_TOKEN_FOR_WEBHOOK"
        mock_bot = MagicMock()
        mock_bot.token = raw
        mock_bot.set_webhook = AsyncMock()

        await configure_webhook_for_bot(mock_bot)

        logger.removeHandler(handler)
        handler.close()
        log_output = stream.getvalue()

        assert raw not in log_output, f"Raw token leaked in configure_webhook log: {log_output}"
        assert mask_token(raw) in log_output

    @pytest.mark.asyncio
    async def test_health_finds_registered_encrypted_token(self, db_session):
        """Диагностический health endpoint сверяет raw token с encrypted token в БД."""
        from backend.database import MasterBot
        from backend.token_utils import encrypt_token
        import backend.webhook as webhook_mod
        from tests.conftest import test_async_session_maker

        raw = "123456:HEALTH_RAW_TOKEN_TEST"
        db_session.add(MasterBot(
            master_telegram_id=777002,
            token=encrypt_token(raw),
            username="health_bot",
            status="running",
        ))
        await db_session.commit()

        with patch.object(webhook_mod, "async_session_maker", test_async_session_maker):
            data = await webhook_mod.webhook_health(raw)

        assert data["ok"] is True
        assert data["username"] == "health_bot"


# ─── admin_commands импорт при отсутствии logs/ ────────────────────────────────


def test_admin_commands_import_creates_logs_dir():
    """Импорт admin_commands создаёт папку logs/ если её нет."""
    import importlib

    orig_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        logs_path = Path(tmpdir) / "logs"
        assert not logs_path.exists()

        import architect.handlers.admin_commands as ac_mod
        importlib.reload(ac_mod)

        assert logs_path.exists(), "logs/ dir should be created on import"

        # Закрываем хендлеры, чтобы tempfile мог удалить папку
        ac_logger = logging.getLogger("admin_commands")
        for h in ac_logger.handlers[:]:
            ac_logger.removeHandler(h)
            h.close()

        os.chdir(orig_cwd)
