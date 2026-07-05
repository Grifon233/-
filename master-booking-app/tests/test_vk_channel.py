import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from architect.services import bot_manager as bot_manager_module
from architect.services import account_link_service as account_link_module
from architect.services import vk_bot_manager as vk_bot_manager_module
from architect.services.account_link_service import account_link_service
from architect.services.bot_manager import bot_manager
from architect.services.vk_bot_manager import vk_bot_manager
from backend.database import (
    Client,
    Master,
    MasterBot,
    MasterVkProfile,
    MenuButton,
    Subscription,
    VkBot,
    VkClientProfile,
    VkClientRegistration,
)
from backend.routers import booking as booking_module
from backend.routers import master as master_router
from backend.token_utils import encrypt_token
from backend.vk import api, architect_bot as vk_architect_module, bot as vk_bot_module
from backend.vk.auth import sign_vk_client_access, verify_vk_client_access
from tests.conftest import test_async_session_maker


def test_vk_client_signature_rejects_tampering_and_expiry():
    now = int(time.time())
    signature = sign_vk_client_access(101, 7, "vk-token", now)
    verify_vk_client_access(101, 7, signature, "vk-token", now, require_fresh=True)

    with pytest.raises(HTTPException) as tampered:
        verify_vk_client_access(102, 7, signature, "vk-token", now, require_fresh=True)
    assert tampered.value.status_code == 401

    with patch("backend.middleware.tg_auth.LINK_TTL_SECONDS", 10):
        old_ts = now - 11
        old_signature = sign_vk_client_access(101, 7, "vk-token", old_ts)
        with pytest.raises(HTTPException) as expired:
            verify_vk_client_access(101, 7, old_signature, "vk-token", old_ts, require_fresh=True)
    assert expired.value.status_code == 401


@pytest.mark.asyncio
async def test_vk_menu_keeps_booking_and_service_buttons_when_custom_menu_is_long(db_session):
    master = Master(id=1, name="Мастер")
    custom_items = [
        {"name": f"Раздел {index}", "icon": "•", "active": True, "texts": ["Текст"]}
        for index in range(12)
    ]
    db_session.add_all([
        master,
        MenuButton(
            master_id=1,
            button_type="custom",
            active=True,
            content_json={"custom_buttons": custom_items},
        ),
    ])
    await db_session.commit()

    with patch.object(vk_bot_module, "async_session_maker", test_async_session_maker):
        keyboard = await vk_bot_module.build_vk_menu(
            1, 101, "Иванов Иван", "vk-token", group_id=55, vk_bot_id=7
        )

    labels = [row[0]["action"]["label"] for row in keyboard["buttons"]]
    assert len(labels) == 10
    assert labels[0] == "📅 Записаться"
    assert labels[-2:] == [
        "ℹ️ Как пользоваться",
        "🤖 Хочу себе такого же бота",
    ]


@pytest.mark.asyncio
async def test_old_vk_link_without_vk_bot_id_can_open_public_master(db_session):
    now = int(time.time())
    master = Master(id=8, name="VK мастер")
    db_session.add_all([
        master,
        VkBot(
            id=9,
            master_id=8,
            master_telegram_id=-808,
            token=encrypt_token("vk-old-link"),
            group_id=808,
            owner_vk_id=808,
            status="running",
        ),
    ])
    await db_session.commit()
    signature = sign_vk_client_access(707, 8, "vk-old-link", now)

    response = await master_router.get_public_master(
        master_id=8,
        db=db_session,
        vk_user=707,
        vk_sig=signature,
        auth_ts=now,
    )

    assert response.success is True
    assert response.data["id"] == 8


@pytest.mark.asyncio
async def test_vk_photo_batch_deduplicates_and_preserves_order():
    async def fake_upload(_token, _peer_id, url):
        await asyncio.sleep(0)
        return None if url.endswith("bad.jpg") else f"photo_{url.rsplit('/', 1)[-1]}"

    with (
        patch.object(api, "upload_photo_batch_for_message", new=AsyncMock(return_value={})),
        patch.object(api, "upload_photo_for_message", side_effect=fake_upload),
    ):
        attachments, failed = await api.upload_photos_for_message(
            "token",
            101,
            ["https://cdn/1.jpg", "https://cdn/bad.jpg", "https://cdn/1.jpg", "https://cdn/2.jpg"],
        )

    assert attachments == ["photo_1.jpg", "photo_2.jpg"]
    assert failed == ["https://cdn/bad.jpg"]


@pytest.mark.asyncio
async def test_vk_photo_batch_uploads_five_and_three_while_preserving_order():
    urls = [f"https://cdn/{index}.jpg" for index in range(8)]

    async def fake_batch(_token, _peer_id, batch):
        return {url: f"photo_{url.rsplit('/', 1)[-1]}" for url in reversed(batch)}

    with (
        patch.object(api, "upload_photo_batch_for_message", side_effect=fake_batch) as batch_upload,
        patch.object(api, "upload_photo_for_message", new=AsyncMock()) as individual_upload,
    ):
        attachments, failed = await api.upload_photos_for_message("token", 101, urls)

    assert [call.args[2] for call in batch_upload.await_args_list] == [urls[:5], urls[5:]]
    assert attachments == [f"photo_{index}.jpg" for index in range(8)]
    assert failed == []
    individual_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_vk_content_does_not_wait_for_photo_upload():
    release_upload = asyncio.Event()

    async def delayed_upload(*_args, **_kwargs):
        await release_upload.wait()
        return "photo1_1"

    send_message = AsyncMock(return_value=True)
    with (
        patch.object(api, "send_message", send_message),
        patch.object(api, "upload_photo_for_message", side_effect=delayed_upload),
    ):
        await asyncio.wait_for(
            vk_bot_module._send_vk_content(
                "token",
                101,
                "Текст доступен сразу",
                ["https://cdn/photo.jpg"],
                {"buttons": []},
            ),
            timeout=0.2,
        )
        assert send_message.await_count == 1
        release_upload.set()
        await asyncio.gather(*list(vk_bot_module._media_tasks))

    assert send_message.await_count == 2
    assert send_message.await_args_list[1].kwargs["attachment"] == "photo1_1"


@pytest.mark.asyncio
async def test_vk_client_registration_creates_global_profile_and_master_client(db_session):
    master = Master(id=20, name="Анна")
    vk_channel = VkBot(
        id=21,
        master_id=20,
        master_telegram_id=500,
        token=encrypt_token("vk-community-token"),
        group_id=700,
        status="running",
    )
    db_session.add_all([master, vk_channel])
    db_session.add(
        MenuButton(
            master_id=20,
            button_type="custom",
            active=True,
            content_json={
                "custom_buttons": [
                    {"name": "Правила", "icon": "📋", "active": True, "texts": ["Текст"]},
                ]
            },
        )
    )
    await db_session.commit()

    send_message = AsyncMock(return_value=True)
    with (
        patch.object(vk_bot_module, "async_session_maker", test_async_session_maker),
        patch.object(api, "send_message", send_message),
    ):
        await vk_bot_module.handle_vk_message(700, {"message": {"from_id": 900, "peer_id": 900, "text": "Начать"}})
        await vk_bot_module.handle_vk_message(700, {"message": {"from_id": 900, "peer_id": 900, "text": "+7 912 345-67-89"}})
        await vk_bot_module.handle_vk_message(700, {"message": {"from_id": 900, "peer_id": 900, "text": "Иванов Иван"}})

    async with test_async_session_maker() as session:
        profile = (await session.execute(select(VkClientProfile).where(VkClientProfile.vk_id == 900))).scalar_one()
        client = (await session.execute(select(Client).where(Client.master_id == 20, Client.vk_id == 900))).scalar_one()
    assert profile.name == "Иванов Иван"
    assert client.phone == profile.phone
    async with test_async_session_maker() as session:
        registration = (await session.execute(
            select(VkClientRegistration).where(
                VkClientRegistration.group_id == 700,
                VkClientRegistration.vk_id == 900,
            )
        )).scalar_one_or_none()
    assert registration is None
    keyboard = send_message.await_args.kwargs["keyboard"]
    labels = [row[0]["action"]["label"] for row in keyboard["buttons"]]
    assert "📅 Записаться" in labels
    assert "📋 Правила" in labels
    architect_button = next(
        row[0]["action"] for row in keyboard["buttons"]
        if row[0]["action"]["label"] == "🤖 Хочу себе такого же бота"
    )
    assert architect_button["link"] == "https://vk.com/club239516667"


@pytest.mark.asyncio
async def test_subscription_status_sync_freezes_and_unfreezes_vk_only_bot(db_session):
    db_session.add(
        VkBot(
            id=31,
            master_id=30,
            master_telegram_id=-12345,
            token=encrypt_token("vk-token"),
            group_id=444,
            status="running",
        )
    )
    await db_session.commit()

    with patch.object(bot_manager_module, "async_session_maker", test_async_session_maker):
        assert await bot_manager.freeze_bot(-12345) is True
        async with test_async_session_maker() as session:
            frozen = await session.get(VkBot, 31)
            assert frozen.status == "frozen"

        assert await bot_manager.unfreeze_bot(-12345) is True
        async with test_async_session_maker() as session:
            running = await session.get(VkBot, 31)
            assert running.status == "running"


@pytest.mark.asyncio
async def test_vk_booking_link_resolves_registered_client(db_session):
    now = int(time.time())
    master = Master(id=40, name="Мария")
    vk_channel = VkBot(
        id=41,
        master_id=40,
        master_telegram_id=-555,
        token=encrypt_token("booking-vk-token"),
        group_id=777,
        status="running",
    )
    profile = VkClientProfile(vk_id=888, name="Петрова Анна", phone="+79123456789")
    db_session.add_all([master, vk_channel, profile])
    await db_session.commit()
    signature = sign_vk_client_access(888, 40, "booking-vk-token", now)

    client = await booking_module._resolve_vk_client(db_session, 40, 888, signature, now)
    await db_session.commit()

    assert client.master_id == 40
    assert client.vk_id == 888
    assert client.name == "Петрова Анна"


@pytest.mark.asyncio
async def test_vk_architect_creates_payment_for_vk_owner():
    class Profile:
        state = "main"
        name = "Анна"
        state_data_json = {}
        pseudo_telegram_id = -123

    payment = {
        "period_label": "1 месяц",
        "amount": 450.0,
        "url": "https://yookassa.example/payment",
    }
    send_message = AsyncMock(return_value=True)
    create_payment = AsyncMock(return_value=payment)
    event = {
        "message": {
            "from_id": 123,
            "peer_id": 123,
            "text": "Оплатить",
            "payload": '{"cmd":"pay_1_month"}',
        }
    }

    with (
        patch.object(vk_architect_module, "_get_or_create_profile", new=AsyncMock(return_value=Profile())),
        patch.object(vk_architect_module, "_has_vk_community_bot", new=AsyncMock(return_value=True)),
        patch.object(vk_architect_module, "_has_tg_bot", new=AsyncMock(return_value=False)),
        patch.object(api, "send_message", send_message),
        patch("architect.services.yookassa_payment.yookassa_payment.create_payment_link", create_payment),
    ):
        await vk_architect_module.handle_vk_architect_message(1, event, "architect-token")

    create_payment.assert_awaited_once_with(-123, "1_month")
    keyboard = send_message.await_args.kwargs["keyboard"]
    assert keyboard["buttons"][0][0]["action"]["link"] == payment["url"]


@pytest.mark.asyncio
async def test_vk_community_owner_gets_master_panel_without_client_registration(db_session):
    db_session.add_all([
        Master(id=50, name="Елена", telegram_id=5050),
        VkBot(
            id=51,
            master_id=50,
            master_telegram_id=5050,
            token=encrypt_token("owner-vk-token"),
            group_id=500,
            owner_vk_id=777,
            status="running",
        ),
    ])
    await db_session.commit()
    send_message = AsyncMock(return_value=True)

    with (
        patch.object(vk_bot_module, "async_session_maker", test_async_session_maker),
        patch.object(api, "send_message", send_message),
    ):
        await vk_bot_module.handle_vk_message(
            500,
            {"message": {"from_id": 777, "peer_id": 777, "text": "Начать"}},
        )

    async with test_async_session_maker() as session:
        profile = (await session.execute(
            select(VkClientProfile).where(VkClientProfile.vk_id == 777)
        )).scalar_one_or_none()
    assert profile is None
    assert "Панель мастера" in send_message.await_args.args[2]
    labels = [
        row[0]["action"]["label"]
        for row in send_message.await_args.kwargs["keyboard"]["buttons"]
    ]
    assert labels == [
        "📅 Календарь",
        "📋 Мои записи",
        "📤 Поделиться ссылкой на бота",
        "🔗 Создать URL-ссылку на бота",
    ]


@pytest.mark.asyncio
async def test_vk_bot_attaches_to_latest_running_telegram_bot_profile(db_session):
    db_session.add_all([
        Master(id=60, name="Первый", telegram_id=6060),
        Master(id=61, name="Второй"),
        MasterBot(
            id=62,
            master_id=60,
            master_telegram_id=6060,
            token=encrypt_token("tg-first"),
            username="first_bot",
            status="running",
        ),
        MasterBot(
            id=63,
            master_id=61,
            master_telegram_id=6060,
            token=encrypt_token("tg-second"),
            username="second_bot",
            status="running",
        ),
    ])
    await db_session.commit()

    with (
        patch.object(vk_bot_manager_module, "async_session_maker", test_async_session_maker),
        patch.object(api, "validate_community_token", new=AsyncMock(return_value={
            "group_id": 606,
            "group_name": "Сообщество",
        })),
        patch.object(api, "get_creator_id", new=AsyncMock(return_value=909)),
    ):
        result = await vk_bot_manager.create_vk_bot(6060, "vk1.community")

    async with test_async_session_maker() as session:
        vk_channel = await session.get(VkBot, result["vk_bot_id"])
    assert vk_channel.master_id == 61
    assert vk_channel.owner_vk_id == 909


@pytest.mark.asyncio
async def test_one_time_vk_link_moves_channel_and_subscription_to_real_telegram_owner(db_session):
    db_session.add_all([
        Master(id=70, name="VK-владелец", telegram_id=-700),
        MasterVkProfile(
            id=71,
            vk_id=700,
            pseudo_telegram_id=-700,
            master_id=70,
            name="VK-владелец",
            state="main",
            state_data_json={},
        ),
        MasterBot(
            id=72,
            master_id=70,
            master_telegram_id=-700,
            token=encrypt_token("tg-linked"),
            username="linked_bot",
            status="running",
        ),
        VkBot(
            id=73,
            master_id=70,
            master_telegram_id=-700,
            token=encrypt_token("vk-linked"),
            group_id=7000,
            owner_vk_id=700,
            status="running",
        ),
        Subscription(
            id=74,
            master_telegram_id=-700,
            master_bot_id=72,
            period_days=30,
            status="active",
        ),
    ])
    await db_session.commit()

    with patch.object(account_link_module, "async_session_maker", test_async_session_maker):
        link = await account_link_service.create_telegram_link(700)
        code = link.split("linkvk_", 1)[1]
        assert await account_link_service.claim_telegram_link(code, 8800) is True
        assert await account_link_service.claim_telegram_link(code, 9900) is False

    async with test_async_session_maker() as session:
        master = await session.get(Master, 70)
        tg_bot = await session.get(MasterBot, 72)
        vk_channel = await session.get(VkBot, 73)
        subscription = await session.get(Subscription, 74)
        vk_profile = await session.get(MasterVkProfile, 71)
    assert master.telegram_id == 8800
    assert tg_bot.master_telegram_id == 8800
    assert vk_channel.master_telegram_id == 8800
    assert subscription.master_telegram_id == 8800
    assert vk_profile.state_data_json["linked_telegram_id"] == 8800
