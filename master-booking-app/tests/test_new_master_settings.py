from datetime import date, time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from backend.database import Booking, Client, ClientProfile, Master, Service
from backend.services.booking_notifications import _weekly_report_text


@pytest.mark.asyncio
async def test_deleted_service_is_archived_and_existing_booking_keeps_snapshot(db_session):
    from backend.routers.admin import delete_service

    master = Master(name="Мастер", telegram_id=901)
    db_session.add(master)
    await db_session.flush()
    service = Service(master_id=master.id, name="Стрижка", price="1500 ₽", duration_minutes=30)
    client = Client(master_id=master.id, telegram_id=902, name="Иванов Иван", phone="+79000000000")
    db_session.add_all([service, client])
    await db_session.flush()
    booking = Booking(
        master_id=master.id,
        client_id=client.id,
        date=date.today(),
        time=time(10, 0),
        ends_at=time(10, 30),
        duration_minutes=30,
        service_id=service.id,
        service_name=service.name,
        service_price_total=1500,
    )
    db_session.add(booking)
    await db_session.commit()

    await delete_service(service.id, db_session, master)
    archived = await db_session.scalar(select(Service).where(Service.id == service.id))
    stored_booking = await db_session.get(Booking, booking.id)

    assert archived.active is False
    assert stored_booking.service_name == "Стрижка"
    assert stored_booking.service_price_total == 1500


def test_weekly_report_contains_new_returning_and_revenue_statistics():
    master = Master(name="Мастер", use_services=True)
    client_new = Client(id=1, master_id=1, name="Новый клиент")
    client_returning = Client(id=2, master_id=1, name="Постоянный клиент")
    rows = [
        (Booking(date=date(2026, 6, 1), duration_minutes=30, service_name="Стрижка", service_price_total=1500, status="completed"), client_new),
        (Booking(date=date(2026, 6, 2), duration_minutes=60, service_name="Укладка", service_price_total=2000, status="completed"), client_returning),
        (Booking(date=date(2026, 6, 3), duration_minutes=30, service_name="Стрижка", service_price_total=1500, status="completed"), client_returning),
    ]

    text = _weekly_report_text(master, rows, date(2026, 6, 1), {2})

    assert "Новых клиентов: <b>1</b>" in text
    assert "Повторных визитов: <b>1</b>" in text
    assert "Доход по указанным ценам: <b>5000 ₽</b>" in text


@pytest.mark.asyncio
async def test_superadmin_can_create_lifetime_subscription(db_session):
    import backend.routers.superadmin as superadmin

    master = Master(name="Пожизненный мастер", telegram_id=903)
    db_session.add(master)
    await db_session.commit()

    with patch.object(superadmin, "verify_superadmin", new=AsyncMock(return_value={"id": 623597334})):
        with patch.object(superadmin.subscription_admin_service, "sync_status", new=AsyncMock()):
            await superadmin.set_subscription(
                master.id,
                request=None,
                payload=superadmin.SubscriptionUpdate(status="active", period_days=30, price=0, lifetime=True),
                db=db_session,
            )
        data = await superadmin.get_masters(request=None, db=db_session, status=None)

    assert data["masters"][0]["subscription"]["lifetime"] is True
    assert data["masters"][0]["subscription"]["ends_at"] is None


@pytest.mark.asyncio
async def test_delete_master_account_removes_owned_data_but_keeps_global_client_profile(db_session):
    from architect.services.bot_manager import bot_manager

    master = Master(name="Удаляемый мастер", telegram_id=904)
    profile = ClientProfile(telegram_id=905, name="Иванов Иван", phone="+79000000000")
    db_session.add_all([master, profile])
    await db_session.flush()
    client = Client(master_id=master.id, telegram_id=profile.telegram_id, name=profile.name, phone=profile.phone)
    service = Service(master_id=master.id, name="Стрижка", price="1500 ₽", duration_minutes=30)
    db_session.add_all([client, service])
    await db_session.flush()
    db_session.add(Booking(
        master_id=master.id,
        client_id=client.id,
        date=date.today(),
        time=time(10, 0),
        ends_at=time(10, 30),
        duration_minutes=30,
        service_name=service.name,
    ))
    await db_session.commit()

    with patch("architect.services.bot_manager.async_session_maker", return_value=db_session):
        assert await bot_manager.delete_master_account(master.telegram_id) is True

    assert await db_session.get(Master, master.id) is None
    assert await db_session.get(ClientProfile, profile.id) is not None
