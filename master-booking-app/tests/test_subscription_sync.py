"""
Тесты для подписок, статусов и заморозки.

Все тесты используют один тестовый engine с in-memory SQLite.
module-level async_session_maker подменяется на тестовый ДО создания db_session,
чтобы функции (get_master_info, sync_status, check_and_remind) читали/писали
в ту же БД, куда тест добавляет данные.
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

# Подменяем module-level async_session_maker на тестовый engine
# Это должно произойти ДО импорта тестируемых функций и ДО вызова db_session fixture.
from tests.conftest import test_async_session_maker
import backend.database as _db_mod
import backend.handlers.master_bot as _mb_mod
import backend.routers.subscription_admin as _sa_mod
import architect.services.subscription_service as _ss_mod

_db_mod.async_session_maker = test_async_session_maker
_mb_mod.async_session_maker = test_async_session_maker
_sa_mod.async_session_maker = test_async_session_maker
_ss_mod.async_session_maker = test_async_session_maker

from backend.database import MasterBot, async_session_maker
from backend.handlers.master_bot import get_master_info


# ─── MasterBot status blocking tests ────────────────────────────────────


class TestMasterBotStatus:
    """Проверка блокировки разных статусов в webhook handler."""

    @pytest.mark.asyncio
    async def test_frozen_bot_returns_none(self, db_session):
        """frozen бот не должен обслуживать webhook."""
        db_session.add(MasterBot(
            master_telegram_id=100,
            token="123:frozen_token_abc",
            status="frozen",
            username="frozen_bot",
        ))
        await db_session.commit()

        info, is_admin = await get_master_info("123:frozen_token_abc", 200)
        assert info is None
        assert is_admin is False

    @pytest.mark.asyncio
    async def test_stopped_bot_returns_none(self, db_session):
        db_session.add(MasterBot(
            master_telegram_id=101,
            token="456:stopped_token_abc",
            status="stopped",
            username="stopped_bot",
        ))
        await db_session.commit()

        info, is_admin = await get_master_info("456:stopped_token_abc", 200)
        assert info is None
        assert is_admin is False

    @pytest.mark.asyncio
    async def test_crashed_bot_returns_none(self, db_session):
        db_session.add(MasterBot(
            master_telegram_id=102,
            token="789:crashed_token_abc",
            status="crashed",
            username="crashed_bot",
        ))
        await db_session.commit()

        info, is_admin = await get_master_info("789:crashed_token_abc", 200)
        assert info is None
        assert is_admin is False

    @pytest.mark.asyncio
    async def test_error_bot_returns_none(self, db_session):
        db_session.add(MasterBot(
            master_telegram_id=103,
            token="111:error_token_abc",
            status="error",
            username="error_bot",
        ))
        await db_session.commit()

        info, is_admin = await get_master_info("111:error_token_abc", 200)
        assert info is None
        assert is_admin is False

    @pytest.mark.asyncio
    async def test_running_bot_returns_info(self, db_session):
        """running бот — возвращает данные мастера, is_admin=True для owner."""
        from backend.database import Master

        db_session.add(Master(
            id=1,
            name="Test Master",
            telegram_id=200,
        ))
        await db_session.flush()

        db_session.add(MasterBot(
            master_telegram_id=200,
            token="222:running_token_abc",
            status="running",
            username="running_bot",
        ))
        await db_session.commit()

        info, is_admin = await get_master_info("222:running_token_abc", 200)
        assert info is not None
        assert info["name"] == "Test Master"
        assert is_admin is True


# ─── SubscriptionAdminService sync_status tests ─────────────────────────


class TestSubscriptionAdminService:
    """Проверка sync_status с замоканным BotManager."""

    @pytest.mark.asyncio
    async def test_sync_status_frozen_calls_freeze_bot(self, db_session):
        """sync_status('frozen') вызывает freeze_bot и ставит frozen."""
        from backend.routers.subscription_admin import subscription_admin_service
        from architect.services.bot_manager import bot_manager

        db_session.add(MasterBot(
            master_telegram_id=300,
            token="333:frozen_test_token",
            status="running",
            username="freeze_test_bot",
        ))
        await db_session.commit()

        with patch.object(bot_manager, "freeze_bot", new=AsyncMock(return_value=True)) as mock_freeze:
            await subscription_admin_service.sync_status(300, "frozen")
            mock_freeze.assert_awaited_once_with(300)

        from tests.conftest import test_async_session_maker
        async with test_async_session_maker() as session:
            result = await session.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == 300)
            )
            bot = result.scalar_one_or_none()
            assert bot is not None
            assert bot.status == "frozen"

    @pytest.mark.asyncio
    async def test_sync_status_active_calls_unfreeze_bot(self, db_session):
        """sync_status('active') вызывает unfreeze_bot, ставит running."""
        from backend.routers.subscription_admin import subscription_admin_service
        from architect.services.bot_manager import bot_manager

        db_session.add(MasterBot(
            master_telegram_id=301,
            token="444:unfreeze_test_token",
            status="frozen",
            username="unfreeze_test_bot",
        ))
        await db_session.commit()

        with patch.object(bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)):
            await subscription_admin_service.sync_status(301, "active")

        from tests.conftest import test_async_session_maker
        async with test_async_session_maker() as session:
            result = await session.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == 301)
            )
            bot = result.scalar_one_or_none()
            assert bot is not None
            assert bot.status == "running"

    @pytest.mark.asyncio
    async def test_sync_status_active_unfreeze_false_sets_error(self, db_session):
        """sync_status('active') при неудачном unfreeze ставит error."""
        from backend.routers.subscription_admin import subscription_admin_service
        from architect.services.bot_manager import bot_manager

        db_session.add(MasterBot(
            master_telegram_id=302,
            token="555:unfreeze_fail_token",
            status="frozen",
            username="unfreeze_fail_bot",
        ))
        await db_session.commit()

        with patch.object(bot_manager, "unfreeze_bot", new=AsyncMock(return_value=False)):
            await subscription_admin_service.sync_status(302, "active")

        from tests.conftest import test_async_session_maker
        async with test_async_session_maker() as session:
            result = await session.execute(
                select(MasterBot).where(MasterBot.master_telegram_id == 302)
            )
            bot = result.scalar_one_or_none()
            assert bot is not None
            assert bot.status == "error"

    @pytest.mark.asyncio
    async def test_sync_status_unknown_raises(self):
        """sync_status с неизвестным статусом — ValueError."""
        from backend.routers.subscription_admin import subscription_admin_service

        with pytest.raises(ValueError):
            await subscription_admin_service.sync_status(999, "unknown_target")


# ─── Subscription expiry tests ──────────────────────────────────────────


class TestSubscriptionExpiry:
    """Проверка что просрочка подписки вызывает freeze_bot, а не stop_bot."""

    @pytest.mark.asyncio
    async def test_check_and_remind_calls_freeze_bot_when_expired(self, db_session):
        """check_and_remind при истекшей подписке вызывает freeze_bot, не stop_bot."""
        from architect.services.subscription_service import subscription_service
        from architect.services.bot_manager import bot_manager
        from backend.database import Subscription, Master

        master = Master(
            name="Expire Master",
            telegram_id=400,
        )
        db_session.add(master)

        sub = Subscription(
            master_telegram_id=400,
            period_days=1,
            status="active",
            paid_at=datetime.now() - timedelta(days=2),
        )
        db_session.add(sub)
        await db_session.commit()

        with patch.object(bot_manager, "freeze_bot", new=AsyncMock(return_value=True)) as mock_freeze:
            with patch.object(bot_manager, "stop_bot", new=AsyncMock()) as mock_stop:
                mock_bot = AsyncMock()
                await subscription_service.check_and_remind(mock_bot)

                # freeze_bot должен быть вызван
                mock_freeze.assert_awaited_once_with(400)
                # stop_bot НЕ должен вызываться
                mock_stop.assert_not_awaited()

        # Статус подписки стал expired
        from tests.conftest import test_async_session_maker
        async with test_async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.master_telegram_id == 400)
            )
            sub = result.scalar_one_or_none()
            assert sub is not None
            assert sub.status == "expired"
