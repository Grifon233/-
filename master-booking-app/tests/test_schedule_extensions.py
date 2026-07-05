from copy import deepcopy
from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.database import DEFAULT_SCHEDULE, Master, MasterBot, Service
from backend.token_utils import encrypt_token
from backend.routers.booking import _validate_schedule_interval
from backend.routers.master import get_availability, get_slots
from backend.time_utils import END_OF_DAY, interval_end


def future_workday() -> date:
    value = date.today() + timedelta(days=1)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def active_schedule() -> dict:
    schedule = deepcopy(DEFAULT_SCHEDULE)
    schedule["days"] = [{**day, "active": True, "break_start": "00:00", "break_end": "00:00"} for day in schedule["days"]]
    return schedule


def test_excluded_date_is_rejected():
    target = future_workday()
    schedule = active_schedule()
    schedule["exceptions"] = [{"start": target.isoformat(), "end": target.isoformat()}]
    master = Master(name="Мастер", schedule_json=schedule)

    with pytest.raises(HTTPException, match="disabled"):
        _validate_schedule_interval(master, target, time(10, 0), 60)


def test_services_may_overrun_workday_only_when_explicitly_allowed():
    target = future_workday()
    master = Master(name="Мастер", schedule_json=active_schedule(), use_services=True)

    with pytest.raises(HTTPException, match="working hours"):
        _validate_schedule_interval(master, target, time(17, 30), 90)

    assert _validate_schedule_interval(master, target, time(17, 30), 90, allow_workday_overrun=True) == time(19, 0)


def test_midnight_interval_uses_single_end_of_day_value():
    assert interval_end(time(23, 0), 60) == END_OF_DAY


@pytest.mark.asyncio
async def test_service_slots_use_requested_duration_and_fifteen_minute_step(db_session):
    master = Master(name="Мастер", telegram_id=10001, schedule_json=active_schedule(), use_services=True, interval_minutes=60)
    db_session.add(master)
    await db_session.flush()
    bot = MasterBot(master_telegram_id=master.telegram_id, token=encrypt_token("100001:TESTTOKEN"), status="running")
    db_session.add(bot)
    await db_session.flush()
    db_session.add(Service(master_id=master.id, name="Стрижка", price="1000 ₽", duration_minutes=30, active=True))
    await db_session.commit()

    response = await get_slots(master.id, future_workday(), 15, db_session, bot.id)
    slots = response.data["slots"]

    assert slots[-1]["time"] == "17:45"
    assert slots[-2]["time"] == "17:30"
    assert response.data["duration"] == 15


@pytest.mark.asyncio
async def test_availability_returns_date_range_in_one_response(db_session, monkeypatch):
    master = Master(name="Мастер", telegram_id=10002, schedule_json=active_schedule(), use_services=True)
    db_session.add(master)
    await db_session.flush()
    bot = MasterBot(
        master_id=master.id,
        master_telegram_id=master.telegram_id,
        token=encrypt_token("100002:TESTTOKEN"),
        status="running",
    )
    db_session.add(bot)
    await db_session.commit()
    monkeypatch.setattr("backend.routers.master.rate_limiter.check", lambda _key: _async_true())

    target = future_workday()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    response = await get_availability(
        master.id,
        target,
        target + timedelta(days=1),
        30,
        request,
        db_session,
        bot_id=bot.id,
    )

    assert set(response.data["availability"]) == {
        target.isoformat(),
        (target + timedelta(days=1)).isoformat(),
    }
    assert response.data["availability"][target.isoformat()] is True


async def _async_true():
    return True
