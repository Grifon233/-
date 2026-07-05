from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.database import Booking, Client, Master, MasterBot, Subscription


@pytest.mark.asyncio
async def test_superadmin_masters_uses_latest_subscription_history(db_session):
    import backend.routers.superadmin as superadmin

    master = Master(name="History Master", telegram_id=701)
    db_session.add(master)
    await db_session.flush()
    db_session.add_all([
        Subscription(master_telegram_id=701, status="expired", period_days=30, created_at=datetime.utcnow() - timedelta(days=2)),
        Subscription(master_telegram_id=701, status="active", period_days=90, created_at=datetime.utcnow()),
        MasterBot(master_telegram_id=701, token="hidden", username="history_bot", status="running"),
    ])
    await db_session.commit()

    with patch.object(superadmin, "verify_superadmin", new=AsyncMock(return_value={"id": 623597334})):
        data = await superadmin.get_masters(request=None, db=db_session, status=None)

    assert data["masters"][0]["subscription"]["status"] == "active"
    assert data["masters"][0]["bot"]["username"] == "history_bot"
    assert "token" not in data["masters"][0]["bot"]


@pytest.mark.asyncio
async def test_superadmin_manual_subscription_and_operational_lists(db_session):
    import backend.routers.superadmin as superadmin

    master = Master(name="Ops Master", telegram_id=702)
    db_session.add(master)
    await db_session.flush()
    client = Client(master_id=master.id, telegram_id=880, name="Иванов Иван", phone="+79000000000")
    db_session.add(client)
    await db_session.flush()
    db_session.add(Booking(
        master_id=master.id,
        client_id=client.id,
        date=date.today(),
        time=time(10, 0),
        ends_at=time(10, 30),
        duration_minutes=30,
        service_name="Стрижка",
        status="upcoming",
    ))
    await db_session.commit()

    with patch.object(superadmin, "verify_superadmin", new=AsyncMock(return_value={"id": 623597334})):
        with patch.object(superadmin.subscription_admin_service, "sync_status", new=AsyncMock()):
            result = await superadmin.set_subscription(
                master.id,
                request=None,
                payload=superadmin.SubscriptionUpdate(status="active", period_days=60, price=900),
                db=db_session,
            )
        bookings = await superadmin.get_bookings(request=None, db=db_session, days=30, status=None, master_id=None, limit=200)
        payments = await superadmin.get_payments(request=None, db=db_session, status=None, limit=200)

    assert result["status"] == "active"
    assert bookings["bookings"][0]["client_name"] == "Иванов Иван"
    assert payments["payments"][0]["payment_provider"] == "manual"
    assert payments["payments"][0]["price"] == 900
