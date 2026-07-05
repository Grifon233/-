from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from architect.services import subscription_service as subscription_service_module
from architect.services import bot_manager as bot_manager_module
from architect.services.bot_manager import bot_manager
from architect.services.subscription_service import subscription_service
from backend.database import Master, MasterBot, Subscription, VkBot
from backend.handlers.master_bot import build_menu, get_custom_button_items, handle_registration_full_name
from backend.routers.master import get_slots
from backend.token_utils import decrypt_token, encrypt_token
from tests.conftest import test_async_session_maker


def _request(path: str = "/api/shorten") -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 12345),
    })


@pytest.mark.asyncio
async def test_short_url_rate_limit_is_checked_before_database_work(db_session):
    from backend.routers import shorten

    with patch.object(shorten.rate_limiter, "check", new=AsyncMock(return_value=False)) as check:
        with pytest.raises(HTTPException) as exc:
            await shorten.shorten_url("https://t.me/example_bot", db_session, _request())

    assert exc.value.status_code == 429
    check.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_restores_frozen_bot_with_active_subscription(db_session):
    now = datetime.utcnow()
    db_session.add_all([
        MasterBot(
            id=501,
            master_telegram_id=700501,
            token=encrypt_token("501:token"),
            username="paid_bot",
            status="frozen",
        ),
        Subscription(
            master_telegram_id=700501,
            master_bot_id=501,
            period_days=30,
            status="active",
            paid_at=now,
        ),
    ])
    await db_session.commit()

    with patch.object(subscription_service_module, "async_session_maker", test_async_session_maker):
        with patch.object(bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)) as unfreeze:
            restored = await subscription_service.reconcile_active_subscription_access()

    assert restored == [501]
    unfreeze.assert_awaited_once_with(700501, 501)


@pytest.mark.asyncio
async def test_master_menu_uses_native_share_url_and_chat_url_callback():
    class FakeUser:
        id = 123
        username = "master"
        first_name = "Master"

    menu = await build_menu(master_id=1, is_admin=True, bot_username="sample_bot", user=FakeUser(), bot_id=77)
    buttons = [row[0] for row in menu.inline_keyboard]

    share = next(button for button in buttons if "Поделиться" in button.text)
    url = next(button for button in buttons if "URL-ссылку" in button.text)
    calendar = next(button for button in buttons if button.text == "📅 Календарь")

    assert share.url.startswith("https://t.me/share/url?")
    assert "sample_bot" in share.url
    assert url.callback_data == "bot_url"
    assert "/calendar" in calendar.url
    assert "bot_id=77" in calendar.url
    assert "master_id=1" in calendar.url


@pytest.mark.asyncio
async def test_trial_cleanup_uses_latest_trial_start(db_session):
    now = datetime.utcnow()
    db_session.add_all([
        MasterBot(
            id=1,
            master_telegram_id=101,
            token="101:recent",
            status="running",
            created_at=now - timedelta(days=5),
            trial_started_at=now,
        ),
        MasterBot(
            id=2,
            master_telegram_id=102,
            token="102:expired",
            status="running",
            created_at=now - timedelta(days=5),
            trial_started_at=now - timedelta(hours=3),
        ),
    ])
    await db_session.commit()

    with (
        patch.object(subscription_service_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_service_module.bot_manager, "delete_bot", new=AsyncMock(return_value=True)) as delete_bot,
    ):
        deleted = await subscription_service.delete_expired_unpaid_trial_bots()

    assert deleted == [2]
    delete_bot.assert_awaited_once_with(102, 2)


@pytest.mark.asyncio
async def test_trial_cleanup_deletes_unpaid_second_bot_even_with_legacy_active_subscription(db_session):
    now = datetime.utcnow()
    db_session.add_all([
        MasterBot(
            id=11,
            master_telegram_id=501,
            token="501:paid",
            status="running",
            created_at=now - timedelta(days=5),
            trial_started_at=now - timedelta(days=5),
        ),
        MasterBot(
            id=12,
            master_telegram_id=501,
            token="501:trial",
            status="running",
            created_at=now - timedelta(hours=3),
            trial_started_at=now - timedelta(hours=3),
        ),
        Subscription(
            master_telegram_id=501,
            master_bot_id=None,
            status="active",
            lifetime=True,
            price=0,
            period_days=3650,
            paid_at=now,
        ),
    ])
    await db_session.commit()

    with (
        patch.object(subscription_service_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_service_module.bot_manager, "delete_bot", new=AsyncMock(return_value=True)) as delete_bot,
    ):
        deleted = await subscription_service.delete_expired_unpaid_trial_bots()

    assert deleted == [12]
    delete_bot.assert_awaited_once_with(501, 12)


@pytest.mark.asyncio
async def test_trial_cleanup_deletes_standalone_vk_bot_and_notifies_in_vk(db_session):
    now = datetime.utcnow()
    db_session.add(VkBot(
        id=91,
        master_id=900,
        master_telegram_id=-9090,
        token=encrypt_token("vk-standalone"),
        group_id=9091,
        group_name="Студия",
        owner_vk_id=9090,
        status="running",
        bot_type="client",
        created_at=now - timedelta(hours=3),
    ))
    await db_session.commit()

    notify = AsyncMock()
    with (
        patch.object(subscription_service_module, "async_session_maker", test_async_session_maker),
        patch("architect.services.vk_bot_manager.async_session_maker", test_async_session_maker),
        patch.object(subscription_service, "_notify_vk_trial_deleted", notify),
    ):
        await subscription_service.delete_expired_unpaid_trial_bots()

    async with test_async_session_maker() as session:
        assert await session.get(VkBot, 91) is None
    notify.assert_awaited_once()
    owner_vk_id, label, source_token = notify.await_args.args
    assert owner_vk_id == 9090
    assert label == "Студия"
    assert decrypt_token(source_token) == "vk-standalone"


@pytest.mark.asyncio
async def test_create_bot_assigns_separate_master_profile_for_second_bot(db_session):
    owner_master = Master(
        id=210,
        telegram_id=90210,
        name="Owner",
        use_services=True,
        interval_minutes=45,
        schedule_json={"booking_days": 90, "days": [], "exceptions": []},
    )
    first_bot = MasterBot(
        id=211,
        master_id=210,
        master_telegram_id=90210,
        token=encrypt_token("90210:first"),
        username="first_bot",
        status="running",
    )
    db_session.add_all([owner_master, first_bot])
    await db_session.commit()

    with (
        patch.object(bot_manager_module, "async_session_maker", test_async_session_maker),
        patch.object(bot_manager, "validate_token", new=AsyncMock(return_value=(True, "second_bot"))),
        patch.object(bot_manager, "configure_webhook_for_bot", new=AsyncMock(return_value=(True, None))),
    ):
        result = await bot_manager.create_bot(90210, "90210:second", "Owner")

    assert result["status"] == "running"
    async with test_async_session_maker() as session:
        second_bot = await session.get(MasterBot, result["bot_id"])
        assert second_bot is not None
        assert second_bot.master_id is not None
        assert second_bot.master_id != owner_master.id
        second_master = await session.get(Master, second_bot.master_id)
        assert second_master is not None
        assert second_master.telegram_id is None
        assert second_master.name == "Owner"


@pytest.mark.asyncio
async def test_subscription_status_can_be_filtered_by_bot(db_session):
    now = datetime.utcnow()
    db_session.add_all([
        Subscription(
            master_telegram_id=7001,
            master_bot_id=1,
            status="active",
            price=450,
            period_days=30,
            paid_at=now,
        ),
        Subscription(
            master_telegram_id=7001,
            master_bot_id=2,
            status="pending",
            price=450,
            period_days=30,
        ),
    ])
    await db_session.commit()

    with patch.object(subscription_service_module, "async_session_maker", test_async_session_maker):
        first = await subscription_service.get_subscription_status(7001, 1)
        second = await subscription_service.get_subscription_status(7001, 2)

    assert first["status"] == "active"
    assert second["status"] == "pending"


@pytest.mark.asyncio
async def test_subscription_expiry_freezes_only_subscription_bot(db_session):
    paid_at = datetime.utcnow() - timedelta(days=31)
    db_session.add(
        Subscription(
            master_telegram_id=7002,
            master_bot_id=22,
            status="active",
            price=450,
            period_days=30,
            paid_at=paid_at,
        )
    )
    await db_session.commit()

    class FakeBot:
        async def send_message(self, *args, **kwargs):
            return None

    with (
        patch.object(subscription_service_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_service_module.bot_manager, "freeze_bot", new=AsyncMock(return_value=True)) as freeze_bot,
    ):
        await subscription_service.check_and_remind(FakeBot())

    freeze_bot.assert_awaited_once_with(7002, 22)


@pytest.mark.asyncio
async def test_public_slots_support_legacy_schedule_without_day_names(db_session):
    tomorrow = datetime.utcnow().date() + timedelta(days=1)
    master = Master(
        id=77,
        telegram_id=770077,
        name="Legacy schedule",
        use_services=False,
        interval_minutes=60,
        schedule_json={
            "days": [
                {"active": True, "work_start": "09:00", "work_end": "18:00", "break_start": "13:00", "break_end": "14:00"}
                for _ in range(7)
            ],
            "booking_days": 90,
            "exceptions": [],
        },
    )
    bot = MasterBot(
        id=77,
        master_telegram_id=770077,
        token="770077:bot",
        status="running",
    )
    db_session.add_all([master, bot])
    await db_session.commit()

    response = await get_slots(
        master_id=77,
        date=tomorrow,
        duration=60,
        db=db_session,
        bot_id=77,
    )

    assert response.success is True
    assert response.data["slots"]


@pytest.mark.asyncio
async def test_client_menu_skips_placeholder_custom_buttons():
    class FakeUser:
        id = 10
        username = "tester"
        first_name = "Tester"

    class FakeScalarResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _query):
            from backend.database import MenuButton

            return FakeScalarResult([
                MenuButton(
                    master_id=1,
                    button_type="custom",
                    active=True,
                    content_json={
                        "custom_buttons": [
                            {"name": "Напишите своё название", "icon": "✨", "active": True, "texts": ["Скрытый черновик"]},
                            {"name": "Правила", "icon": "📋", "active": True, "texts": ["Без опозданий"]},
                        ]
                    },
                )
            ])

    with patch("backend.handlers.master_bot.async_session_maker", return_value=FakeSession()):
        menu = await build_menu(master_id=1, is_admin=False, bot_token="1:token", user=FakeUser(), bot_username="sample_bot", bot_id=1)

    labels = [row[0].text for row in menu.inline_keyboard]
    assert "✨ Напишите своё название" not in labels
    assert "📋 Правила" in labels


def test_custom_button_items_support_legacy_nested_content():
    assert get_custom_button_items({
        "content": {
            "custom_buttons": [{"name": "Правила", "active": True}]
        }
    }) == [{"name": "Правила", "active": True}]


@pytest.mark.asyncio
async def test_client_menu_shows_active_custom_button_even_if_parent_flag_is_off():
    class FakeUser:
        id = 10
        username = "tester"
        first_name = "Tester"

    class FakeScalarResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, _query):
            from backend.database import MenuButton

            return FakeScalarResult([
                MenuButton(
                    master_id=1,
                    button_type="custom",
                    active=False,
                    content_json={
                        "custom_buttons": [
                            {"name": "Правила", "icon": "📋", "active": True, "texts": ["Без опозданий"]},
                        ]
                    },
                )
            ])

    with patch("backend.handlers.master_bot.async_session_maker", return_value=FakeSession()):
        menu = await build_menu(master_id=1, is_admin=False, bot_token="1:token", user=FakeUser(), bot_username="sample_bot", bot_id=1)

    labels = [row[0].text for row in menu.inline_keyboard]
    assert "📋 Правила" in labels


@pytest.mark.asyncio
async def test_registration_creates_master_client_binding_for_profile_links(db_session):
    from backend.database import Master, MasterBot, Client

    master = Master(id=91, name="Master", telegram_id=910091)
    bot = MasterBot(id=91, master_telegram_id=910091, token="91:token", status="running")
    db_session.add_all([master, bot])
    await db_session.commit()

    class FakeState:
        async def get_data(self):
            return {"phone": "+79000000011"}

        async def clear(self):
            return None

        async def set_state(self, _value):
            return None

    class FakeBotInfo:
        username = "sample_bot"

    class FakeBot:
        token = "91:token"

        async def get_me(self):
            return FakeBotInfo()

    class FakeUser:
        id = 111001
        username = "client_user"

    class FakeMessage:
        from_user = FakeUser()
        text = "иванов иван"

        def __init__(self):
            self.answers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

    message = FakeMessage()

    with patch("backend.handlers.master_bot.async_session_maker", test_async_session_maker):
        await handle_registration_full_name(message, FakeState(), FakeBot())

    async with test_async_session_maker() as session:
        client = (await session.execute(
            select(Client).where(Client.master_id == master.id, Client.telegram_id == FakeUser.id)
        )).scalar_one_or_none()

    assert client is not None
    assert client.name == "Иванов Иван"
