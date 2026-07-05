from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from backend.client_profiles import normalize_full_name
from backend.database import Master
from backend.routers.booking import _price_to_int, _validate_schedule_interval
from backend.routers.slots import create_slot_hold


def test_price_parser_uses_first_amount_without_joining_digits():
    assert _price_to_int("1 500.50 ₽") == 1500
    assert _price_to_int("1000 - 1500 ₽") == 1000
    assert _price_to_int("от 2000 ₽") == 2000


def test_full_name_allows_real_names_without_vowels():
    assert normalize_full_name("ким и") == "Ким И"
    assert normalize_full_name("пак цзэн") == "Пак Цзэн"


@pytest.mark.asyncio
async def test_slot_hold_rejects_excessive_duration(db_session):
    with pytest.raises(HTTPException, match="duration_minutes"):
        await create_slot_hold(
            db=db_session,
            master_id=1,
            slot_date=date.today() + timedelta(days=1),
            slot_time=__import__("datetime").time(9, 0),
            session_id="test-session",
            duration_minutes=1440,
        )


def test_schedule_validation_uses_master_timezone():
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    local_now = datetime.now(ZoneInfo("Asia/Vladivostok"))
    if local_now.hour == 0:
        pytest.skip("The previous minute belongs to another date")
    requested = time(local_now.hour - 1, 0)
    master = Master(
        name="Тест",
        timezone="Asia/Vladivostok",
        schedule_json={
            "booking_days": 90,
            "days": [{"day": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][local_now.weekday()], "active": True, "work_start": "00:00", "work_end": "23:59", "break_start": "00:00", "break_end": "00:00"}],
        },
    )
    with pytest.raises(HTTPException, match="Cannot book in the past"):
        _validate_schedule_interval(master, local_now.date(), requested, 15)
