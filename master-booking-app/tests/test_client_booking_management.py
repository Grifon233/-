import time as _time
from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.client_profiles import save_client_profile, sign_client_access


def _fresh_sig(user_id, master_id, token):
    """Свежая подпись клиентской ссылки (auth_ts = сейчас)."""
    auth_ts = int(_time.time())
    return auth_ts, sign_client_access(user_id, master_id, token, auth_ts)
from backend.database import Booking, BookingStatusHistory, Client, Master, MasterBot
from backend.routers.booking import client_cancel_booking, client_reschedule_booking, get_client_bookings


ALL_DAYS_SCHEDULE = {
    "days": [
        {
            "day": day,
            "active": True,
            "work_start": "09:00",
            "work_end": "18:00",
            "break_start": "13:00",
            "break_end": "14:00",
        }
        for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ]
}


class JsonRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


async def seed_client_booking(db_session, *, master_id=80, telegram_id=8001):
    token = f"BOT_TOKEN_{master_id}"
    master = Master(
        id=master_id,
        name="Client Actions Master",
        telegram_id=master_id * 100,
        schedule_json=ALL_DAYS_SCHEDULE,
    )
    db_session.add(master)
    db_session.add(MasterBot(master_telegram_id=master.telegram_id, token=token, status="running"))
    profile = await save_client_profile(db_session, telegram_id, "client", "+79000000001", "Иванов Иван")
    client = Client(master_id=master_id, telegram_id=profile.telegram_id, name=profile.name, phone=profile.phone)
    db_session.add(client)
    await db_session.flush()
    booking = Booking(
        master_id=master_id,
        client_id=client.id,
        date=date.today() + timedelta(days=2),
        time=time(10, 0),
        ends_at=time(11, 0),
        duration_minutes=60,
        service_name="Стрижка",
        status="upcoming",
        comment="Позвонить заранее",
    )
    db_session.add(booking)
    await db_session.commit()
    return master, client, booking, token


@pytest.mark.asyncio
async def test_client_lists_only_own_future_bookings(db_session):
    master, client, booking, token = await seed_client_booking(db_session)
    other = Client(master_id=master.id, telegram_id=8002, name="Петров Пётр", phone="+79000000002")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Booking(
        master_id=master.id,
        client_id=other.id,
        date=date.today() + timedelta(days=3),
        time=time(11, 0),
        ends_at=time(12, 0),
        duration_minutes=60,
        status="upcoming",
    ))
    await db_session.commit()

    auth_ts, sig = _fresh_sig(client.telegram_id, master.id, token)
    response = await get_client_bookings(
        master_id=master.id,
        telegram_user_id=client.telegram_id,
        client_sig=sig,
        auth_ts=auth_ts,
        telegram_init_data=None,
        db=db_session,
    )

    assert [item["id"] for item in response.data["bookings"]] == [booking.id]
    assert response.data["bookings"][0]["comment"] == "Позвонить заранее"


@pytest.mark.asyncio
async def test_client_cannot_cancel_another_clients_booking(db_session):
    master, _, booking, token = await seed_client_booking(db_session)
    await save_client_profile(db_session, 8002, "other", "+79000000002", "Петров Пётр")
    other = Client(master_id=master.id, telegram_id=8002, name="Петров Пётр", phone="+79000000002")
    db_session.add(other)
    await db_session.commit()

    auth_ts, sig = _fresh_sig(other.telegram_id, master.id, token)
    with pytest.raises(HTTPException) as exc:
        await client_cancel_booking(
            booking.id,
            JsonRequest({
                "master_id": master.id,
                "telegram_user_id": other.telegram_id,
                "client_sig": sig,
                "auth_ts": auth_ts,
            }),
            db_session,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_client_cancel_records_optional_comment_and_notifies_master(db_session):
    master, client, booking, token = await seed_client_booking(db_session)
    with patch("backend.routers.booking._send_client_action_notification", new=AsyncMock()) as notify:
        auth_ts, sig = _fresh_sig(client.telegram_id, master.id, token)
        response = await client_cancel_booking(
            booking.id,
            JsonRequest({
                "master_id": master.id,
                "telegram_user_id": client.telegram_id,
                "client_sig": sig,
                "auth_ts": auth_ts,
                "comment": "Не успеваю приехать",
            }),
            db_session,
        )

    history = (await db_session.execute(
        select(BookingStatusHistory).where(BookingStatusHistory.booking_id == booking.id)
    )).scalar_one()
    assert response.data["status"] == "cancelled"
    assert history.changed_by == "client"
    assert history.reason == "Не успеваю приехать"
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_reschedule_updates_booking_and_history(db_session):
    master, client, booking, token = await seed_client_booking(db_session)
    new_date = date.today() + timedelta(days=4)
    with patch("backend.routers.booking._send_client_action_notification", new=AsyncMock()) as notify:
        auth_ts, sig = _fresh_sig(client.telegram_id, master.id, token)
        response = await client_reschedule_booking(
            booking.id,
            JsonRequest({
                "master_id": master.id,
                "telegram_user_id": client.telegram_id,
                "client_sig": sig,
                "auth_ts": auth_ts,
                "new_date": new_date.isoformat(),
                "new_time": "11:00",
                "comment": "Удобнее после обеда",
            }),
            db_session,
        )

    history = (await db_session.execute(
        select(BookingStatusHistory).where(BookingStatusHistory.booking_id == booking.id)
    )).scalar_one()
    assert response.data["date"] == new_date.isoformat()
    assert response.data["time"] == "11:00"
    assert history.changed_by == "client"
    assert "Удобнее после обеда" in history.reason
    notify.assert_awaited_once()
