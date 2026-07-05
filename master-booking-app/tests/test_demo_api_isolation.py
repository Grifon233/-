#!/usr/bin/env python3
"""
Тесты на изоляцию демо API от реальных мастеров и проверка клиентской идентификации.
"""
import pytest
from datetime import date, timedelta
from sqlalchemy import select

from backend.database import Master, get_demo_master, DEMO_MASTER_ID, DEMO_MASTER_TELEGRAM_ID, seed_master, Client, Booking, DEFAULT_SCHEDULE


def next_workday() -> str:
    value = date.today() + timedelta(days=1)
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value.isoformat()


@pytest.mark.asyncio
async def test_demo_api_uses_actual_demo_master_when_real_master_exists(db_session):
    """Тест: демо API использует фактического демо-мастера, когда real Master(id=1) существует."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        telegram_id=123456789,
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()

    demo_master = await get_demo_master(session)

    assert demo_master.id != real_master.id
    assert demo_master.id == DEMO_MASTER_ID
    assert demo_master.is_demo is True
    assert demo_master.telegram_id == DEMO_MASTER_TELEGRAM_ID
    assert demo_master.avatar_url == "/demo-avatar.jpg"
    assert real_master.is_demo is False


@pytest.mark.asyncio
async def test_demo_services_read_from_demo_master_not_real(db_session):
    """Тест: /api/demo/services читает услуги демо-мастера, а не реального id=1."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()

    demo_master = await get_demo_master(session)

    assert demo_master.id != real_master.id
    assert demo_master.id == DEMO_MASTER_ID

    from backend.routers.demo import demo_services

    response = await demo_services(db=session)

    assert response.success is True
    assert "services" in response.data

    services = response.data["services"]
    assert len(services) >= 3
    assert any(s["name"] == "💇 Стрижка" for s in services)


@pytest.mark.asyncio
async def test_demo_bookings_master_read_from_demo_master_not_real(db_session):
    """Тест: /api/demo/bookings/master читает записи демо-мастера, а не реального id=1."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()

    demo_master = await get_demo_master(session)

    assert demo_master.id != real_master.id
    assert demo_master.id == DEMO_MASTER_ID

    from backend.routers.demo import demo_master_bookings

    response = await demo_master_bookings(db=session)

    assert response.success is True
    assert "bookings" in response.data

    bookings = response.data["bookings"]
    assert len(bookings) > 0
    for booking in bookings:
        assert booking["master_id"] == demo_master.id
        assert booking["master_id"] != real_master.id


@pytest.mark.asyncio
async def test_demo_master_endpoint_returns_actual_demo_master(db_session):
    """Тест: /api/demo/master возвращает фактического демо-мастера."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()

    demo_master_obj = await get_demo_master(session)

    from backend.routers.demo import demo_master

    response = await demo_master(db=session)

    assert response.success is True
    assert response.data["id"] == demo_master_obj.id
    assert response.data["avatar_url"] == "/demo-avatar.jpg"
    assert response.data["id"] != real_master.id
    assert response.data["is_demo"] is True


@pytest.mark.asyncio
async def test_demo_master_created_with_id_1_when_free(db_session):
    """Тест: демо-мастер создаётся с id=1, если он свободен."""
    session = db_session

    demo_master = await get_demo_master(session)

    assert demo_master.id == 1
    assert demo_master.is_demo is True
    assert demo_master.telegram_id == DEMO_MASTER_TELEGRAM_ID


@pytest.mark.asyncio
async def test_demo_master_created_with_id_999_when_id_1_occupied(db_session):
    """Тест: демо-мастер создаётся с id=999, если id=1 занят реальным мастером."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()

    demo_master = await get_demo_master(session)

    assert demo_master.id == DEMO_MASTER_ID
    assert demo_master.is_demo is True
    assert demo_master.telegram_id == DEMO_MASTER_TELEGRAM_ID
    assert real_master.is_demo is False


@pytest.mark.asyncio
async def test_booking_requires_bot_registration_for_real_master(db_session):
    """Публичная запись требует предварительную регистрацию через Telegram-бота."""
    session = db_session

    # Мастер с рабочим расписанием — чтобы проверка дошла до контактов
    real_master = Master(
        id=2,
        name="Реальный Мастер",
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    # Пробуем создать запись без контактной информации — должна быть ошибка
    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 2,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "",  # Пустое имя
            },
            session,
        )
    assert "регистрац" in str(exc_info.value).lower()

    # Пробуем создать запись без телефона и Telegram
    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 2,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "Тестовый Клиент",
                "client_phone": "",  # Нет телефона
                "telegram_init_data": None,  # Нет Telegram
            },
            session,
        )
    assert "регистрац" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_booking_with_manual_phone_is_rejected(db_session):
    """Публичная форма не может подменить подтверждённый Telegram contact ручным телефоном."""
    session = db_session

    real_master = Master(
        id=3,
        name="Реальный Мастер",
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 3,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "Тестовый Клиент",
                "client_phone": "+79001234567",
            },
            session,
        )
    assert "регистрац" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_booking_demo_mode_does_not_save(db_session):
    """Тест: запись в демо режиме не сохраняется в БД."""
    session = db_session

    demo_master = await get_demo_master(session)

    from backend.routers.booking import _create_booking_logic

    # Считаем записи до
    result = await session.execute(
        select(Booking).where(Booking.master_id == demo_master.id)
    )
    count_before = len(result.scalars().all())

    response = await _create_booking_logic(
        {
            "master_id": demo_master.id,
            "date": next_workday(),
            "time": "10:00",
            "client_name": "Тестовый Клиент",
            "client_phone": "+79001234567",
        },
        session,
    )

    assert response.success is True
    assert response.data["demo_mode"] is True

    # Считаем записи после — должно быть то же количество
    result = await session.execute(
        select(Booking).where(Booking.master_id == demo_master.id)
    )
    count_after = len(result.scalars().all())

    assert count_after == count_before, (
        f"Demo booking should not increase count: before={count_before}, after={count_after}"
    )


@pytest.mark.asyncio
async def test_booking_with_invalid_phone_rejected(db_session):
    """Тест: запись с некорректным телефоном отклоняется."""
    session = db_session

    real_master = Master(
        id=4,
        name="Реальный Мастер",
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    # Пробуем создать запись с некорректным телефоном (менее 10 цифр)
    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 4,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "Тестовый Клиент",
                "client_phone": "123",  # Менее 10 цифр
            },
            session,
        )
    assert "регистрац" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_booking_arbitrary_contact_data_not_saved(db_session):
    """Произвольные данные формы без подписи бота не создают клиента."""
    session = db_session

    real_master = Master(
        id=5,
        name="Реальный Мастер",
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    with pytest.raises(Exception):
        await _create_booking_logic(
            {
                "master_id": 5,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "Клиент С Телеграмом",
                "client_phone": "+79001234567",
            },
            session,
        )

    result = await session.execute(select(Client).where(Client.master_id == 5))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_registered_profile_is_reused_for_two_masters(db_session):
    """Один Telegram-профиль регистрируется один раз, карточки мастеров остаются раздельными."""
    from backend.client_profiles import save_client_profile, sign_client_access
    from backend.database import ClientProfile, MasterBot
    from backend.routers.booking import _create_booking_logic

    session = db_session
    for master_id, owner_id, token, booking_time in [
        (6, 6001, "BOT_TOKEN_6", "10:00"),
        (7, 7001, "BOT_TOKEN_7", "11:00"),
    ]:
        session.add(Master(
            id=master_id,
            name=f"Мастер {master_id}",
            telegram_id=owner_id,
            is_demo=False,
            schedule_json=DEFAULT_SCHEDULE,
            interval_minutes=60,
        ))
        session.add(MasterBot(master_telegram_id=owner_id, token=token, status="running"))
    await save_client_profile(session, 555001, "client_user", "+79001234567", "Иванов Иван")
    await session.commit()

    import time as _time
    for master_id, token, booking_time in [(6, "BOT_TOKEN_6", "10:00"), (7, "BOT_TOKEN_7", "11:00")]:
        auth_ts = int(_time.time())
        response = await _create_booking_logic(
            {
                "master_id": master_id,
                    "date": next_workday(),
                "time": booking_time,
                "telegram_user_id": 555001,
                "client_sig": sign_client_access(555001, master_id, token, auth_ts),
                "auth_ts": auth_ts,
            },
            session,
        )
        assert response.success is True

    profiles = (await session.execute(select(ClientProfile))).scalars().all()
    clients = (await session.execute(select(Client).where(Client.telegram_id == 555001))).scalars().all()
    assert len(profiles) == 1
    assert {client.master_id for client in clients} == {6, 7}
    assert all(client.name == "Иванов Иван" and client.phone == "+79001234567" for client in clients)


# =============================================================================
# Tests for admin booking endpoint (POST /api/bookings/admin)
# =============================================================================

@pytest.mark.asyncio
async def test_admin_booking_uses_master_id_from_auth_not_body(db_session):
    """Тест: admin handler берёт master_id из авторизации, а не из body."""
    session = db_session

    real_master = Master(
        id=1,
        name="Реальный Мастер",
        telegram_id=123456789,
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import admin_create_booking

    class MockRequest:
        async def json(self):
            return {
                "master_id": 999,  # Подменили — должен быть заменён на auth master_id=1
                    "date": next_workday(),
                "time": "10:00",
                "client_name": "Клиент Админ",
                "client_phone": "+79001234567",
            }

    # Вызываем handler напрямую, передавая master=real_master вместо verify_master_access
    response = await admin_create_booking(
        request=MockRequest(),
        db=session,
        master=real_master,
    )

    assert response.success is True
    booking_id = response.data["id"]
    booking = await session.get(Booking, booking_id)
    # master_id должен быть 1 (из auth), а не 999 (из body)
    assert booking.master_id == real_master.id


@pytest.mark.asyncio
async def test_admin_booking_accepts_master_comment(db_session):
    """Тест: admin endpoint принимает master_comment."""
    session = db_session

    real_master = Master(
        id=2,
        name="Мастер",
        telegram_id=987654321,
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    response = await _create_booking_logic(
        {
            "master_id": 2,
            "date": next_workday(),
            "time": "11:00",
            "client_name": "Клиент С Заметкой",
            "client_phone": "+79001234567",
            "master_comment": "Заметка мастера",
        },
        session,
        is_admin=True,
    )

    assert response.success is True
    booking_id = response.data["id"]
    booking = await session.get(Booking, booking_id)
    assert booking.master_comment == "Заметка мастера"


@pytest.mark.asyncio
async def test_public_endpoint_rejects_master_comment(db_session):
    """Тест: публичный endpoint отклоняет master_comment."""
    session = db_session

    real_master = Master(
        id=3,
        name="Мастер Публичный",
        telegram_id=111222333,
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 3,
                "date": "2026-06-03",
                "time": "12:00",
                "client_name": "Клиент",
                "client_phone": "+79001234567",
                "master_comment": "Попытка добавить заметку",
            },
            session,
            is_admin=False,
        )
    assert "master_comment not allowed" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_admin_booking_demo_mode_does_not_save(db_session):
    """Тест: admin запись в демо режиме не сохраняется в БД."""
    session = db_session

    demo_master = await get_demo_master(session)

    from backend.routers.booking import _create_booking_logic

    result = await session.execute(
        select(Booking).where(Booking.master_id == demo_master.id)
    )
    count_before = len(result.scalars().all())

    response = await _create_booking_logic(
        {
            "master_id": demo_master.id,
            "date": next_workday(),
            "time": "10:00",
            "client_name": "Демо Клиент",
            "client_phone": "+79001234567",
        },
        session,
        is_admin=True,
    )

    assert response.success is True
    assert response.data["demo_mode"] is True

    result = await session.execute(
        select(Booking).where(Booking.master_id == demo_master.id)
    )
    count_after = len(result.scalars().all())

    assert count_after == count_before, (
        f"Demo admin booking should not increase count: before={count_before}, after={count_after}"
    )


@pytest.mark.asyncio
async def test_admin_booking_requires_client_name(db_session):
    """Тест: admin endpoint требует client_name."""
    session = db_session

    real_master = Master(
        id=4,
        name="Мастер",
        telegram_id=444555666,
        is_demo=False,
        schedule_json=DEFAULT_SCHEDULE,
        use_services=False,
        interval_minutes=60,
    )
    session.add(real_master)
    await session.commit()

    from backend.routers.booking import _create_booking_logic

    with pytest.raises(Exception) as exc_info:
        await _create_booking_logic(
            {
                "master_id": 4,
                "date": next_workday(),
                "time": "10:00",
                "client_name": "",  # Пустое имя
                "client_phone": "+79001234567",
            },
            session,
            is_admin=True,
        )
    assert "client_name required" in str(exc_info.value).lower()
