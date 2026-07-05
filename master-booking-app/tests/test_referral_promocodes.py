from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import architect.services.referral_service as referral_module
import architect.services.subscription_service as subscription_module
from architect.services.referral_service import referral_service
from architect.services.subscription_service import subscription_service
from backend.database import MasterBot, ReferralApplication, ReferralCode, Subscription
from tests.conftest import test_async_session_maker


@pytest.mark.asyncio
async def test_referral_code_is_stable_and_self_code_is_rejected(db_session):
    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        code = await referral_service.ensure_code(1001)
        same_code = await referral_service.ensure_code(1001)
        result = await referral_service.apply_code(1001, code)

    assert code == same_code
    assert len(code) == 4
    assert code.isdigit()
    assert result.ok is False
    assert "собственный" in result.message


@pytest.mark.asyncio
async def test_referral_code_cannot_be_used_after_first_payment(db_session):
    db_session.add_all([
        ReferralCode(telegram_id=2001, code="1234"),
        Subscription(
            master_telegram_id=2002,
            period_days=30,
            price=450,
            payment_provider="manual",
            payment_id="paid-before",
            status="active",
            paid_at=datetime.utcnow(),
        ),
    ])
    await db_session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        result = await referral_service.apply_code(2002, "1234")

    assert result.ok is False
    assert "до первой оплаты" in result.message


@pytest.mark.asyncio
async def test_referral_bonus_is_added_once_after_first_payment(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=3001, code="4321"),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=3001,
            referred_telegram_id=3002,
            status="applied",
        ),
        Subscription(
            master_telegram_id=3001,
            period_days=30,
            price=450,
            payment_provider="manual",
            payment_id="referrer-paid",
            status="active",
            paid_at=datetime.utcnow(),
        ),
        Subscription(
            master_telegram_id=3002,
            period_days=30,
            price=450,
            payment_provider="telegram_yookassa",
            payment_id="new-payment",
            status="pending",
        ),
    ])
    await db_session.commit()

    with (
        patch.object(subscription_module, "async_session_maker", test_async_session_maker),
        patch.object(referral_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_module.bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)),
        patch.object(subscription_service, "_notify_payment_success", new=AsyncMock()),
    ):
        sub = await subscription_service.activate_pending_subscription("telegram_yookassa", "new-payment")
        repeated = await referral_service.reward_after_payment("telegram_yookassa", "new-payment")

    assert sub is not None
    async with test_async_session_maker() as session:
        referred = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 3002)
        )).scalars().first()
        referrer = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 3001)
        )).scalars().first()
        application = (await session.execute(select(ReferralApplication))).scalars().first()

    assert referred.period_days == 60
    assert referrer.period_days == 60
    assert application.status == "rewarded"
    assert repeated["rewarded"] is False


@pytest.mark.asyncio
async def test_referral_code_cannot_be_replaced_before_payment(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=4001, code="1111"),
        ReferralCode(id=2, telegram_id=4002, code="2222"),
    ])
    await db_session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        first = await referral_service.apply_code(4003, "1111")
        second = await referral_service.apply_code(4003, "2222")

    async with test_async_session_maker() as session:
        application = (await session.execute(
            select(ReferralApplication).where(ReferralApplication.referred_telegram_id == 4003)
        )).scalars().first()

    assert first.ok is True
    assert second.ok is False
    assert "уже использовали" in second.message
    assert application.referrer_telegram_id == 4001


@pytest.mark.asyncio
async def test_referrer_receives_accumulated_months_from_multiple_referred_masters(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=5001, code="5555"),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=5001,
            referred_telegram_id=5002,
            status="applied",
        ),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=5001,
            referred_telegram_id=5003,
            status="applied",
        ),
        Subscription(
            master_telegram_id=5001,
            master_bot_id=10,
            period_days=30,
            price=450,
            payment_provider="manual",
            payment_id="referrer-active",
            status="active",
            paid_at=datetime.utcnow(),
        ),
        Subscription(
            master_telegram_id=5002,
            master_bot_id=20,
            period_days=30,
            price=450,
            payment_provider="yookassa_checkout",
            payment_id="payment-5002",
            status="pending",
        ),
        Subscription(
            master_telegram_id=5003,
            master_bot_id=30,
            period_days=180,
            price=2700,
            payment_provider="yookassa_checkout",
            payment_id="payment-5003",
            status="pending",
        ),
    ])
    await db_session.commit()

    with (
        patch.object(subscription_module, "async_session_maker", test_async_session_maker),
        patch.object(referral_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_module.bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)),
        patch.object(subscription_service, "_notify_payment_success", new=AsyncMock()),
    ):
        first = await subscription_service.activate_pending_subscription("yookassa_checkout", "payment-5002")
        second = await subscription_service.activate_pending_subscription("yookassa_checkout", "payment-5003")
        repeated = await referral_service.reward_after_payment("yookassa_checkout", "payment-5002")

    assert first is not None
    assert second is not None
    async with test_async_session_maker() as session:
        referrer = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 5001)
        )).scalars().first()
        referred_one = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 5002)
        )).scalars().first()
        referred_two = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 5003)
        )).scalars().first()
        applications = (await session.execute(
            select(ReferralApplication).order_by(ReferralApplication.referred_telegram_id)
        )).scalars().all()

    assert referrer.period_days == 90
    assert referred_one.period_days == 60
    assert referred_two.period_days == 210
    assert [item.status for item in applications] == ["rewarded", "rewarded"]
    assert repeated["rewarded"] is False


@pytest.mark.asyncio
async def test_referrer_without_paid_subscription_gets_bonus_on_own_latest_bot(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=6001, code="6001"),
        MasterBot(
            id=61,
            master_telegram_id=6001,
            token="token-old",
            username="oldbot",
            status="running",
        ),
        MasterBot(
            id=62,
            master_telegram_id=6001,
            token="token-new",
            username="newbot",
            status="running",
        ),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=6001,
            referred_telegram_id=6002,
            status="applied",
        ),
        Subscription(
            master_telegram_id=6002,
            master_bot_id=70,
            period_days=30,
            price=450,
            payment_provider="telegram_yookassa",
            payment_id="payment-6002",
            status="pending",
        ),
    ])
    await db_session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        reward = await referral_service.reward_after_payment("telegram_yookassa", "payment-6002")

    async with test_async_session_maker() as session:
        referred = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 6002)
        )).scalars().first()
        referrer_bonus = (await session.execute(
            select(Subscription).where(
                Subscription.master_telegram_id == 6001,
                Subscription.payment_provider == "promo_bonus",
            )
        )).scalars().first()

    assert reward["rewarded"] is True
    assert referred.period_days == 60
    assert referrer_bonus is not None
    assert referrer_bonus.master_bot_id == 62
    assert referrer_bonus.period_days == 30


@pytest.mark.asyncio
async def test_referral_bonus_is_revoked_after_referred_payment_refund(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=7001, code="7001"),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=7001,
            referred_telegram_id=7002,
            status="applied",
        ),
        Subscription(
            master_telegram_id=7001,
            master_bot_id=71,
            period_days=30,
            price=450,
            payment_provider="manual",
            payment_id="referrer-paid-7001",
            status="active",
            paid_at=datetime.utcnow(),
        ),
        Subscription(
            master_telegram_id=7002,
            master_bot_id=72,
            period_days=30,
            price=450,
            payment_provider="yookassa_checkout",
            payment_id="payment-7002",
            status="pending",
        ),
    ])
    await db_session.commit()

    with (
        patch.object(subscription_module, "async_session_maker", test_async_session_maker),
        patch.object(referral_module, "async_session_maker", test_async_session_maker),
        patch.object(subscription_module.bot_manager, "unfreeze_bot", new=AsyncMock(return_value=True)),
        patch.object(subscription_module.bot_manager, "freeze_bot", new=AsyncMock(return_value=True)),
        patch.object(subscription_service, "_notify_payment_success", new=AsyncMock()),
        patch.object(subscription_service, "_notify_refund", new=AsyncMock()),
    ):
        paid = await subscription_service.activate_pending_subscription("yookassa_checkout", "payment-7002")
        refunded = await subscription_service.mark_subscription_refunded("yookassa_checkout", "payment-7002")
        repeated = await referral_service.revoke_reward_after_refund(paid.id)

    assert paid is not None
    assert refunded is not None
    async with test_async_session_maker() as session:
        referrer = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 7001)
        )).scalars().first()
        referred = (await session.execute(
            select(Subscription).where(Subscription.master_telegram_id == 7002)
        )).scalars().first()
        application = (await session.execute(select(ReferralApplication))).scalars().first()

    assert referred.status == "refunded"
    assert referred.period_days == 30
    assert referrer.period_days == 30
    assert application.status == "reward_revoked"
    assert repeated["revoked"] is False


@pytest.mark.asyncio
async def test_get_applied_code_returns_code_while_pending_and_none_after_reward(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=8001, code="8001"),
        ReferralApplication(
            id=1,
            code_id=1,
            referrer_telegram_id=8001,
            referred_telegram_id=8002,
            status="applied",
        ),
    ])
    await db_session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        code_before = await referral_service.get_applied_code(8002)

    async with test_async_session_maker() as session:
        app = await session.get(ReferralApplication, 1)
        app.status = "rewarded"
        await session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        code_after = await referral_service.get_applied_code(8002)

    assert code_before == "8001"
    assert code_after is None


@pytest.mark.asyncio
async def test_own_code_always_visible_even_when_applied_code_exists(db_session):
    db_session.add_all([
        ReferralCode(id=1, telegram_id=9001, code="9001"),
        ReferralCode(id=2, telegram_id=9002, code="9002"),
        ReferralApplication(
            code_id=1,
            referrer_telegram_id=9001,
            referred_telegram_id=9002,
            status="applied",
        ),
    ])
    await db_session.commit()

    with patch.object(referral_module, "async_session_maker", test_async_session_maker):
        own_code = await referral_service.ensure_code(9002)
        applied_code = await referral_service.get_applied_code(9002)

    assert own_code == "9002"
    assert applied_code == "9001"
