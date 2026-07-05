"""
Тесты защиты от двойной записи, rate limit и SlotHold.

Все используют in-memory SQLite.
"""
from datetime import date, time, datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import select

ALL_DAYS_SCHEDULE = {
    "days": [{"day": d, "active": True, "work_start": "09:00", "work_end": "18:00",
              "break_start": "13:00", "break_end": "14:00"}
             for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]]
}

# Поделки на тестовый engine
from tests.conftest import test_async_session_maker
import backend.database as _db_mod
import backend.routers.booking as _bk_mod
import backend.routers.master as _mr_mod
import backend.rate_limiter as _rl_mod

_db_mod.async_session_maker = test_async_session_maker
_bk_mod.async_session_maker = test_async_session_maker
_mr_mod.async_session_maker = test_async_session_maker
_rl_mod.async_session_maker = test_async_session_maker  # если будет async_session в rate_limiter

from backend.database import Master, Booking, Client, Service, SlotHold, Base
from backend.routers.booking import _create_booking_logic, acquire_slot_lock
from backend.time_utils import time_overlaps, intervals_overlap, interval_end


# ─── Rate limiter tests ──────────────────────────────────────────────


class TestRateLimiter:
    """In-memory rate limiter (Redis fallback)."""

    @pytest.mark.asyncio
    async def test_first_request_allowed(self):
        from backend.rate_limiter import InMemoryRateStore
        store = InMemoryRateStore()
        assert await store.check_and_increment("1.2.3.4") is True

    @pytest.mark.asyncio
    async def test_exceed_limit_blocked(self):
        from backend.rate_limiter import InMemoryRateStore, RATE_LIMIT_REQUESTS
        store = InMemoryRateStore()
        ip = "1.2.3.5"
        for _ in range(RATE_LIMIT_REQUESTS):
            assert await store.check_and_increment(ip) is True
        # Превышение
        assert await store.check_and_increment(ip) is False

    @pytest.mark.asyncio
    async def test_rate_limiter_interface_uses_memory(self):
        """rate_limiter.check без REDIS_URL должен работать через in-memory."""
        from backend.rate_limiter import rate_limiter
        # принудительно memory
        rate_limiter._use_redis = False
        ip = "1.2.3.6"
        assert await rate_limiter.check(ip) is True


# ─── SlotHold tests ──────────────────────────────────────────────────


class TestSlotHold:
    """Проверка что SlotHold блокирует слот в get_slots и create_booking."""

    @pytest.mark.asyncio
    async def test_hold_blocks_slot_in_get_slots(self, db_session):
        """Активный hold помечает слот как недоступный."""
        from backend.routers.master import get_slots

        master = Master(id=1, telegram_id=10001, name="Test Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        from backend.database import MasterBot
        from backend.token_utils import encrypt_token
        bot = MasterBot(master_telegram_id=master.telegram_id, token=encrypt_token("100001:TESTTOKEN"), status="running")
        db_session.add(bot)
        await db_session.commit()

        # Дата, которая точно рабочий день
        next_day = date.today() + timedelta(days=1)

        # Hold создаём напрямую в db_session
        from backend.database import SlotHold
        db_session.add(SlotHold(
            master_id=1,
            date=next_day,
            time=time(10, 0),
            duration_minutes=60,
            session_id="test_session",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        await db_session.commit()

        slots_resp = await get_slots(1, next_day, 60, db_session, bot.id)
        slots = slots_resp.data["slots"]
        slot_10 = next((s for s in slots if s["time"] == "10:00"), None)
        assert slot_10 is not None
        assert slot_10["available"] is False
        assert slot_10["reason"] == "held"  # hold должен перекрывать booked

    @pytest.mark.asyncio
    async def test_expired_hold_does_not_block(self, db_session):
        """Просроченный hold не блокирует слот."""
        from backend.routers.master import get_slots

        master = Master(id=2, telegram_id=10002, name="Test Master 2", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        from backend.database import MasterBot
        from backend.token_utils import encrypt_token
        bot = MasterBot(master_telegram_id=master.telegram_id, token=encrypt_token("100002:TESTTOKEN"), status="running")
        db_session.add(bot)
        await db_session.commit()

        next_day = date.today() + timedelta(days=1)

        # Hold в той же db_session
        from backend.database import SlotHold
        db_session.add(SlotHold(
            master_id=2,
            date=next_day,
            time=time(10, 0),
            duration_minutes=60,
            session_id="test_session",
            expires_at=datetime.utcnow() - timedelta(minutes=5),  # expired
        ))
        await db_session.commit()

        slots_resp = await get_slots(2, next_day, 60, db_session, bot.id)
        slots = slots_resp.data["slots"]
        slot_10 = next((s for s in slots if s["time"] == "10:00"), None)
        assert slot_10 is not None
        assert slot_10["available"] is True

    @pytest.mark.asyncio
    async def test_create_hold_api(self, db_session):
        """POST /slots/hold создаёт hold."""
        from backend.routers.slots import create_slot_hold

        master = Master(id=3, name="Hold Master", interval_minutes=60, is_demo=True,
                        schedule_json={"days": []})
        db_session.add(master)
        await db_session.commit()

        resp = await create_slot_hold(
            db=db_session,
            master_id=3,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(14, 0),
            session_id="user_100",
            duration_minutes=60,
        )
        assert resp.success is True
        assert resp.data["hold_id"] > 0
        assert resp.data["ttl_minutes"] == 5

    @pytest.mark.asyncio
    async def test_hold_release_api(self, db_session):
        """DELETE /slots/hold/{id} удаляет hold."""
        from backend.routers.slots import create_slot_hold, release_slot_hold

        master = Master(id=4, name="Release Master", interval_minutes=60, is_demo=True,
                        schedule_json={"days": []})
        db_session.add(master)
        await db_session.commit()

        resp = await create_slot_hold(
            db=db_session,
            master_id=4,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(15, 0),
            session_id="user_101",
            duration_minutes=60,
        )
        hold_id = resp.data["hold_id"]

        release_resp = await release_slot_hold(
            hold_id=hold_id,
            session_id="user_101",
            db=db_session,
        )
        assert release_resp.success is True
        assert release_resp.data["released"] is True

    @pytest.mark.asyncio
    async def test_foreign_session_cannot_release(self, db_session):
        """Чужой session_id не может освободить hold."""
        from backend.routers.slots import create_slot_hold, release_slot_hold
        from fastapi import HTTPException

        master = Master(id=5, name="Foreign Master", interval_minutes=60, is_demo=True,
                        schedule_json={"days": []})
        db_session.add(master)
        await db_session.commit()

        resp = await create_slot_hold(
            db=db_session,
            master_id=5,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(16, 0),
            session_id="owner",
            duration_minutes=60,
        )
        hold_id = resp.data["hold_id"]

        with pytest.raises(HTTPException) as exc:
            await release_slot_hold(
                hold_id=hold_id,
                session_id="attacker",
                db=db_session,
            )
        assert exc.value.status_code == 403


# ─── Concurrent booking protection tests ──────────────────────────────


class TestConcurrentBooking:
    """Проверка защиты от двойной записи на один слот."""

    @pytest.mark.asyncio
    async def test_double_booking_same_slot_rejected(self, db_session):
        """Две записи на один слот — вторая отклоняется."""
        master = Master(id=10, name="Concurrent Master", interval_minutes=60,
                        schedule_json={
                            "days": [{"day": d, "active": True, "work_start": "09:00", "work_end": "18:00",
                                      "break_start": "13:00", "break_end": "14:00"}
                                     for d in ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]]
                        })
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=10, name="Test", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        next_day = date.today() + timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += timedelta(days=2)

        payload = {
            "master_id": 10,
            "date": next_day.isoformat(),
            "time": "10:00:00",
            "service_ids": [svc.id],
            "client_name": "Client A",
            "client_phone": "+7 900 000-00-01",
        }

        # Первая запись — OK
        resp1 = await _create_booking_logic(payload, db_session, is_admin=True)
        assert resp1.success is True

        # Вторая запись на тот же слот — должна быть 409
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await _create_booking_logic(payload, db_session, is_admin=True)
        assert exc.value.status_code == 409
        assert "already booked" in exc.value.detail

    @pytest.mark.asyncio
    async def test_overlapping_duration_rejected(self, db_session):
        """Пересечение по длительности (не только одинаковое время)."""
        master = Master(id=11, name="Overlap Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc_long = Service(master_id=11, name="Long Service", price="200", duration_minutes=90)
        db_session.add(svc_long)
        svc_short = Service(master_id=11, name="Short Service", price="50", duration_minutes=30)
        db_session.add(svc_short)
        await db_session.commit()

        next_day = date.today() + timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += timedelta(days=2)

        # Запись на 10:00 длительностью 90 мин (до 11:30)
        payload1 = {
            "master_id": 11,
            "date": next_day.isoformat(),
            "time": "10:00:00",
            "service_ids": [svc_long.id],
            "client_name": "Client Long",
            "client_phone": "+7 900 000-00-02",
        }
        resp1 = await _create_booking_logic(payload1, db_session, is_admin=True)
        assert resp1.success is True

        # Попытка записи на 11:00 длительностью 30 мин (пересечение 11:00-11:30 с 10:00-11:30)
        payload2 = {
            "master_id": 11,
            "date": next_day.isoformat(),
            "time": "11:00:00",
            "service_ids": [svc_short.id],
            "client_name": "Client Short",
            "client_phone": "+7 900 000-00-03",
        }
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await _create_booking_logic(payload2, db_session, is_admin=True)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_non_overlapping_slot_accepted(self, db_session):
        """Непересекающиеся слоты — обе записи проходят."""
        master = Master(id=12, name="NonOverlap Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=12, name="Standard", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        next_day = date.today() + timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += timedelta(days=2)

        payload1 = {
            "master_id": 12,
            "date": next_day.isoformat(),
            "time": "10:00:00",
            "service_ids": [svc.id],
            "client_name": "Client 1",
            "client_phone": "+7 900 000-00-10",
        }
        resp1 = await _create_booking_logic(payload1, db_session, is_admin=True)
        assert resp1.success is True

        # 11:00 — не пересекается с 10:00-11:00
        payload2 = {
            "master_id": 12,
            "date": next_day.isoformat(),
            "time": "11:00:00",
            "service_ids": [svc.id],
            "client_name": "Client 2",
            "client_phone": "+7 900 000-00-11",
        }
        resp2 = await _create_booking_logic(payload2, db_session, is_admin=True)
        assert resp2.success is True

    @pytest.mark.asyncio
    async def test_advisory_lock_rejects_duplicate(self, db_session):
        """Повторная запись на занятый слот отклоняется после lock."""
        master = Master(id=13, name="Advisory Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=13, name="Quick", price="50", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        next_day = date.today() + timedelta(days=1)
        if next_day.weekday() == 6:
            next_day += timedelta(days=2)

        payload = {
            "master_id": 13,
            "date": next_day.isoformat(),
            "time": "09:00:00",
            "service_ids": [svc.id],
            "client_name": "Race Client",
            "client_phone": "+7 900 000-00-20",
        }

        # Первая запись
        resp1 = await _create_booking_logic(payload, db_session, is_admin=True)
        assert resp1.success is True

        # Вторая — должна быть 409
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await _create_booking_logic(payload, db_session, is_admin=True)

    @pytest.mark.asyncio
    async def test_booking_outside_working_hours_rejected(self, db_session):
        """API must not accept a direct request outside the visible schedule."""
        from fastapi import HTTPException

        master = Master(id=14, name="Schedule Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await _create_booking_logic({
                "master_id": 14,
                "date": (date.today() + timedelta(days=2)).isoformat(),
                "time": "18:00:00",
                "client_name": "Late Client",
                "client_phone": "+7 900 000-00-21",
            }, db_session, is_admin=True)

        assert exc.value.status_code == 400
        assert "working hours" in exc.value.detail

    @pytest.mark.asyncio
    async def test_admin_update_cannot_move_booking_over_existing_booking(self, db_session):
        """The generic admin update endpoint must not bypass reschedule logic."""
        from fastapi import HTTPException
        from backend.routers.admin import update_booking

        master = Master(id=15, name="Admin Update Master", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.flush()
        client = Client(master_id=15, name="Admin Client", phone="+7 900 000-00-22")
        db_session.add(client)
        await db_session.flush()
        target_date = date.today() + timedelta(days=2)
        first = Booking(
            master_id=15, client_id=client.id, date=target_date,
            time=time(10, 0), ends_at=time(11, 0), duration_minutes=60,
            status="upcoming",
        )
        second = Booking(
            master_id=15, client_id=client.id, date=target_date,
            time=time(12, 0), ends_at=time(13, 0), duration_minutes=60,
            status="upcoming",
        )
        db_session.add_all([first, second])
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await update_booking(
                booking_id=second.id,
                data={"time": "10:30"},
                db=db_session,
                master=master,
            )

        assert exc.value.status_code == 400
        assert "переноса" in exc.value.detail

    @pytest.mark.asyncio
    async def test_admin_update_cannot_resurrect_cancelled_booking(self, db_session):
        from fastapi import HTTPException
        from backend.routers.admin import update_booking

        master = Master(id=16, name="Status Master")
        client = Client(master_id=16, name="Status Client", phone="+7 900 000-00-23")
        db_session.add_all([master, client])
        await db_session.flush()
        booking = Booking(
            master_id=master.id,
            client_id=client.id,
            date=date.today() + timedelta(days=2),
            time=time(10, 0),
            ends_at=time(11, 0),
            duration_minutes=60,
            status="cancelled",
        )
        db_session.add(booking)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await update_booking(
                booking_id=booking.id,
                data={"status": "upcoming"},
                db=db_session,
                master=master,
            )

        assert exc.value.status_code == 409
        assert "cancelled -> upcoming" in exc.value.detail


# ─── Time overlap helper tests ───────────────────────────────────────


class TestTimeOverlap:
    """Юнит-тесты _time_overlaps."""

    def test_exact_overlap(self):
        assert time_overlaps(time(10, 0), time(11, 0), time(10, 0), time(11, 0)) is True

    def test_partial_overlap(self):
        assert time_overlaps(time(10, 0), time(11, 0), time(10, 30), time(11, 30)) is True

    def test_no_overlap_before(self):
        assert time_overlaps(time(10, 0), time(11, 0), time(11, 0), time(12, 0)) is False

    def test_no_overlap_after(self):
        assert time_overlaps(time(11, 0), time(12, 0), time(10, 0), time(11, 0)) is False

    def test_contained(self):
        assert time_overlaps(time(10, 0), time(12, 0), time(10, 30), time(11, 0)) is True


# ─── SlotHold overlap tests ────────────────────────────────────────


class TestSlotHoldOverlap:
    """Hold с пересечением интервалов, не точного времени."""

    @pytest.mark.asyncio
    async def test_hold_overlap_10_00_90min_blocks_10_30_30min(self, db_session):
        """Hold 10:00 на 90 мин блокирует hold 10:30 на 30 мин (чужая сессия)."""
        from backend.routers.slots import create_slot_hold
        from fastapi import HTTPException

        master = Master(id=20, name="Overlap Hold", is_demo=True, schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        resp = await create_slot_hold(
            db=db_session, master_id=20,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(10, 0), session_id="user_a", duration_minutes=90,
        )
        assert resp.success is True

        with pytest.raises(HTTPException) as exc:
            await create_slot_hold(
                db=db_session, master_id=20,
                slot_date=date.today() + timedelta(days=2),
                slot_time=time(10, 30), session_id="user_b", duration_minutes=30,
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_hold_non_overlap_11_30_OK(self, db_session):
        """Hold 10:00-11:30, hold 11:30-12:00 — не пересекаются."""
        from backend.routers.slots import create_slot_hold

        master = Master(id=21, name="NonOverlap Hold", is_demo=True, schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        resp1 = await create_slot_hold(
            db=db_session, master_id=21,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(10, 0), session_id="user_c", duration_minutes=90,
        )
        assert resp1.success is True

        resp2 = await create_slot_hold(
            db=db_session, master_id=21,
            slot_date=date.today() + timedelta(days=2),
            slot_time=time(11, 30), session_id="user_d", duration_minutes=30,
        )
        assert resp2.success is True


# ─── Booking vs SlotHold tests ─────────────────────────────────────


class TestBookingVsHold:
    """Проверка что create_booking учитывает активные hold."""

    @pytest.mark.asyncio
    async def test_booking_rejected_when_hold_overlaps_no_session(self, db_session):
        """Hold 10:00 на 90 мин — booking 10:30 без session_id -> 409."""
        from fastapi import HTTPException

        master = Master(id=30, name="Hold Block Booking", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=30, name="Test", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        db_session.add(SlotHold(
            master_id=30,
            date=date.today() + timedelta(days=2),
            time=time(10, 0), duration_minutes=90,
            session_id="holder",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await _create_booking_logic({
                "master_id": 30,
                "date": (date.today() + timedelta(days=2)).isoformat(),
                "time": "10:30:00",
                "service_ids": [svc.id],
                "client_name": "Victim",
                "client_phone": "+7 900 000-00-30",
            }, db_session, is_admin=True)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_booking_with_own_hold_passes(self, db_session):
        """Тот же session_id что у hold — запись проходит."""
        master = Master(id=31, name="Own Hold Pass", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=31, name="Test", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        my_session = "my_session_123"
        db_session.add(SlotHold(
            master_id=31,
            date=date.today() + timedelta(days=2),
            time=time(10, 0), duration_minutes=90,
            session_id=my_session,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        await db_session.commit()

        resp = await _create_booking_logic({
            "master_id": 31,
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "time": "10:00:00",
            "service_ids": [svc.id],
            "client_name": "Owner",
            "client_phone": "+7 900 000-00-31",
            "session_id": my_session,
        }, db_session, is_admin=True)
        assert resp.success is True

    @pytest.mark.asyncio
    async def test_expired_hold_does_not_block_booking(self, db_session):
        """Просроченный hold не блокирует запись."""
        master = Master(id=32, name="Expired Hold", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE)
        db_session.add(master)
        await db_session.commit()

        svc = Service(master_id=32, name="Test", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        db_session.add(SlotHold(
            master_id=32,
            date=date.today() + timedelta(days=2),
            time=time(10, 0), duration_minutes=90,
            session_id="old_holder",
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        ))
        await db_session.commit()

        resp = await _create_booking_logic({
            "master_id": 32,
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "time": "10:00:00",
            "service_ids": [svc.id],
            "client_name": "New Client",
            "client_phone": "+7 900 000-00-32",
        }, db_session, is_admin=True)
        assert resp.success is True

    @pytest.mark.asyncio
    async def test_public_booking_accepts_null_comment(self, db_session):
        """Frontend отправляет comment=null; backend не должен падать 500."""
        from backend.client_profiles import save_client_profile, sign_client_access
        from backend.database import MasterBot

        master = Master(id=33, name="Null Comment", interval_minutes=60,
                        schedule_json=ALL_DAYS_SCHEDULE, telegram_id=3300)
        db_session.add(master)
        db_session.add(MasterBot(master_telegram_id=3300, token="BOT_TOKEN_33", status="running"))
        await save_client_profile(db_session, 3333, "null_comment", "+79000000033", "Иванов Иван")
        await db_session.commit()

        svc = Service(master_id=33, name="Test", price="100", duration_minutes=60)
        db_session.add(svc)
        await db_session.commit()

        import time as _time
        auth_ts = int(_time.time())
        resp = await _create_booking_logic({
            "master_id": 33,
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "time": "10:00:00",
            "service_ids": [svc.id],
            "telegram_user_id": 3333,
            "client_sig": sign_client_access(3333, 33, "BOT_TOKEN_33", auth_ts),
            "auth_ts": auth_ts,
            "comment": None,
        }, db_session, is_admin=False)

        assert resp.success is True


# ─── Stable lock key tests ─────────────────────────────────────────


class TestStableLockKey:
    """Стабильность _stable_lock_key между вызовами."""

    def test_same_input_same_key(self):
        from backend.routers.booking import _stable_lock_key
        d = date(2026, 6, 15)
        k1 = _stable_lock_key(1, d, 100600)
        k2 = _stable_lock_key(1, d, 100600)
        assert k1 == k2
        assert isinstance(k1, int)

    def test_different_input_different_key(self):
        from backend.routers.booking import _stable_lock_key
        d = date(2026, 6, 15)
        k1 = _stable_lock_key(1, d, 100600)
        k2 = _stable_lock_key(2, d, 100600)
        assert k1 != k2

    def test_key_fits_postgresql_bigint(self):
        from backend.routers.booking import _stable_lock_key

        key = _stable_lock_key(1, date.today(), 100600)
        assert -(2 ** 63) <= key < 2 ** 63


def test_anonymous_slot_hold_routes_are_not_published():
    """Slot holds stay internal until the frontend has an authenticated session flow."""
    from backend.main import app

    paths = {route.path for route in app.routes}
    assert "/api/slots/hold" not in paths
    assert "/api/slots/holds/cleanup" not in paths
