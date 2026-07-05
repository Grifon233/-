from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from tests.conftest import test_async_session_maker


@pytest.mark.asyncio
async def test_yookassa_create_payment_link_creates_telegram_invoice_and_pending_subscription(db_session):
    import architect.services.yookassa_payment as payment_module
    from backend.database import Subscription

    bot = AsyncMock()
    bot.create_invoice_link.return_value = "https://t.me/$invoice"
    bot.session.close = AsyncMock()

    with patch.object(payment_module, "async_session_maker", test_async_session_maker):
        with patch.object(payment_module, "Bot", return_value=bot):
            with patch.object(payment_module.settings, "architect_token", "architect-token"):
                with patch.dict("os.environ", {"YOOKASSA_PROVIDER_TOKEN": "provider-token"}, clear=False):
                    payment = await payment_module.yookassa_payment.create_payment_link(12345, "1_month")

    assert payment["amount"] == 450.0
    assert payment["url"] == "https://t.me/$invoice"
    bot.create_invoice_link.assert_awaited_once()
    kwargs = bot.create_invoice_link.await_args.kwargs
    assert kwargs["provider_token"] == "provider-token"
    assert kwargs["currency"] == "RUB"
    assert kwargs["prices"][0].amount == 45000

    async with test_async_session_maker() as session:
        subscription = (
            await session.execute(select(Subscription).where(Subscription.payment_id == payment["payload"]))
        ).scalar_one()
    assert subscription.payment_provider == "telegram_yookassa"
    assert subscription.status == "pending"


@pytest.mark.asyncio
async def test_yookassa_create_payment_link_uses_external_checkout_when_api_credentials_exist(db_session):
    import architect.services.yookassa_payment as payment_module
    from backend.database import ClientProfile, Subscription

    db_session.add(ClientProfile(
        telegram_id=12345,
        telegram_username="payer",
        phone="+79000000001",
        name="Иванов Иван",
    ))
    await db_session.commit()

    response = {
        "id": "payment-123",
        "status": "pending",
        "confirmation": {"confirmation_url": "https://yookassa.example/checkout"},
    }

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return response

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self.post_args = args
            self.post_kwargs = kwargs
            return FakeResponse()

    with patch.object(payment_module, "async_session_maker", test_async_session_maker):
        with patch.object(payment_module.httpx, "AsyncClient", FakeAsyncClient):
            with patch.dict("os.environ", {"YOOKASSA_SHOP_ID": "1369263", "YOOKASSA_SECRET_KEY": "live_secret"}, clear=False):
                payment = await payment_module.yookassa_payment.create_payment_link(12345, "6_months")

    assert payment["url"] == "https://yookassa.example/checkout"
    assert payment["checkout_mode"] == "external"
    async with test_async_session_maker() as session:
        subscription = (
            await session.execute(select(Subscription).where(Subscription.payment_id == "payment-123"))
        ).scalar_one()
    assert subscription.payment_provider == "yookassa_checkout"
    assert subscription.status == "pending"
    assert subscription.telegram_payment_charge_id == payment["payload"]


@pytest.mark.asyncio
async def test_yookassa_external_checkout_requires_receipt_contact(db_session):
    import architect.services.yookassa_payment as payment_module

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HTTP client should not be created without receipt contact")

    with patch.object(payment_module, "async_session_maker", test_async_session_maker):
        with patch.object(payment_module.httpx, "AsyncClient", FakeAsyncClient):
            with patch.dict("os.environ", {"YOOKASSA_SHOP_ID": "1369263", "YOOKASSA_SECRET_KEY": "live_secret"}, clear=False):
                with pytest.raises(ValueError):
                    await payment_module.yookassa_payment.create_payment_link(54321, "1_month")


@pytest.mark.asyncio
async def test_yookassa_pre_checkout_rejects_foreign_user_or_changed_amount(db_session):
    import architect.services.yookassa_payment as payment_module
    from backend.database import Subscription

    payload = "yookassa:12345:1_month:nonce"
    db_session.add(Subscription(
        master_telegram_id=12345,
        period_days=30,
        price=450,
        payment_provider="telegram_yookassa",
        payment_id=payload,
        status="pending",
    ))
    await db_session.commit()

    with patch.object(payment_module, "async_session_maker", test_async_session_maker):
        assert await payment_module.yookassa_payment.validate_order(99999, payload, "RUB", 45000)
        assert await payment_module.yookassa_payment.validate_order(12345, payload, "RUB", 1)
        assert await payment_module.yookassa_payment.validate_order(12345, payload, "RUB", 45000) is None


def test_yookassa_has_all_specified_subscription_periods():
    import architect.services.yookassa_payment as payment_module

    plans = payment_module.yookassa_payment.PLANS
    assert set(plans) == {"1_month", "6_months", "12_months"}
    assert plans["6_months"].amount_minor == 270000


@pytest.mark.asyncio
async def test_yookassa_successful_payment_activates_subscription_and_saves_charge_ids(db_session):
    import architect.services.subscription_service as subscription_module
    import architect.services.referral_service as referral_module
    import architect.services.yookassa_payment as payment_module
    from architect.services.bot_manager import bot_manager
    from backend.database import Subscription

    payload = "yookassa:12345:12_months:nonce"
    db_session.add(Subscription(
        master_telegram_id=12345,
        period_days=365,
        price=5300,
        payment_provider="telegram_yookassa",
        payment_id=payload,
        status="pending",
    ))
    await db_session.commit()

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=12345),
        successful_payment=SimpleNamespace(
            invoice_payload=payload,
            currency="RUB",
            total_amount=530000,
            telegram_payment_charge_id="telegram-charge",
            provider_payment_charge_id="provider-charge",
        ),
        answer=AsyncMock(),
    )

    with patch.object(payment_module, "async_session_maker", test_async_session_maker):
        with patch.object(subscription_module, "async_session_maker", test_async_session_maker):
            with patch.object(referral_module, "async_session_maker", test_async_session_maker):
                with patch.object(bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)):
                    activated = await payment_module.yookassa_payment.handle_successful_payment(
                        message,
                        subscription_module.subscription_service,
                    )

    assert activated is True
    message.answer.assert_awaited_once()
    async with test_async_session_maker() as session:
        subscription = (
            await session.execute(select(Subscription).where(Subscription.payment_id == payload))
        ).scalar_one()
    assert subscription.status == "active"
    assert subscription.paid_at is not None
    assert subscription.telegram_payment_charge_id == "telegram-charge"
    assert subscription.provider_payment_charge_id == "provider-charge"


@pytest.mark.asyncio
async def test_yookassa_refund_marks_subscription_refunded_and_freezes_bot(db_session):
    import architect.services.subscription_service as subscription_module
    from architect.services.subscription_service import subscription_service
    from backend.database import MasterBot, Subscription

    db_session.add(MasterBot(
        id=77,
        master_telegram_id=777001,
        token="777:token",
        username="refund_bot",
        status="running",
    ))
    db_session.add(Subscription(
        master_telegram_id=777001,
        master_bot_id=77,
        period_days=30,
        price=450,
        payment_provider="yookassa_checkout",
        payment_id="payment-refund",
        status="active",
    ))
    await db_session.commit()

    with patch.object(subscription_module, "async_session_maker", test_async_session_maker):
        with patch.object(subscription_module.bot_manager, "freeze_bot", new=AsyncMock(return_value=True)) as freeze_bot:
            with patch.object(subscription_service, "_notify_refund", new=AsyncMock()):
                refunded = await subscription_service.mark_subscription_refunded(
                    "yookassa_checkout",
                    "payment-refund",
                    refund_id="refund-1",
                    refund_amount="450.00",
                )

    assert refunded is not None
    freeze_bot.assert_awaited_once_with(777001, 77)
    async with test_async_session_maker() as session:
        subscription = (
            await session.execute(select(Subscription).where(Subscription.payment_id == "payment-refund"))
        ).scalar_one()
    assert subscription.status == "refunded"
    assert subscription.provider_payment_charge_id == "refund:refund-1"


@pytest.mark.asyncio
async def test_yookassa_refund_keeps_bot_running_when_another_subscription_is_active(db_session):
    import architect.services.subscription_service as subscription_module
    from architect.services.subscription_service import subscription_service
    from backend.database import MasterBot, Subscription

    db_session.add(MasterBot(
        id=78,
        master_telegram_id=778001,
        token="778:token",
        username="paid_bot",
        status="running",
    ))
    db_session.add_all([
        Subscription(
            master_telegram_id=778001,
            master_bot_id=78,
            period_days=30,
            price=450,
            payment_provider="yookassa_checkout",
            payment_id="payment-old",
            status="active",
        ),
        Subscription(
            master_telegram_id=778001,
            master_bot_id=78,
            period_days=180,
            price=2700,
            payment_provider="yookassa_checkout",
            payment_id="payment-new",
            status="active",
        ),
    ])
    await db_session.commit()

    with patch.object(subscription_module, "async_session_maker", test_async_session_maker):
        with patch.object(subscription_module.bot_manager, "freeze_bot", new=AsyncMock(return_value=True)) as freeze_bot:
            with patch.object(subscription_service, "_notify_refund", new=AsyncMock()):
                await subscription_service.mark_subscription_refunded("yookassa_checkout", "payment-old")

    freeze_bot.assert_not_called()
    async with test_async_session_maker() as session:
        statuses = {
            row.payment_id: row.status
            for row in (await session.execute(select(Subscription))).scalars().all()
        }
    assert statuses["payment-old"] == "refunded"
    assert statuses["payment-new"] == "active"
