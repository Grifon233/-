#!/usr/bin/env python3
"""
Тесты на изоляцию демо и реальных данных.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import Master, seed_master, ensure_demo_content, DEMO_MASTER_ID


@pytest.mark.asyncio
async def test_seed_master_creates_demo_master_without_touching_real_master(db_session):
    """Тест: seed_master не трогает реального мастера id=1, если он существует."""
    session = db_session
    
    # Создаём реального мастера (id=1, is_demo=False)
    real_master = Master(
        id=1,
        name="Реальный Мастер",
        telegram_id=123456789,
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()
    
    # Запускаем seed_master
    await seed_master(session)
    
    # Проверяем, что реальный мастер не изменился
    result = await session.execute(select(Master).where(Master.id == 1))
    master_1 = result.scalar_one()
    assert master_1.name == "Реальный Мастер"
    assert master_1.is_demo is False
    
    # Проверяем, что создан демо-мастер (может быть id=1 или DEMO_MASTER_ID)
    result = await session.execute(select(Master).where(Master.is_demo == True))
    demo_master = result.scalar_one()
    assert demo_master.is_demo is True
    assert demo_master.name == "Анна, демо-мастер"


@pytest.mark.asyncio
async def test_ensure_demo_content_raises_error_on_non_demo_master(db_session):
    """Тест: ensure_demo_content выбрасывает ошибку на не-демомастере."""
    session = db_session
    
    # Создаём реального мастера
    real_master = Master(
        id=2,
        name="Реальный Мастер",
        is_demo=False,
    )
    session.add(real_master)
    await session.commit()
    
    # Проверяем, что ensure_demo_content выбрасывает ошибку
    with pytest.raises(ValueError, match="ensure_demo_content can only be called on demo masters"):
        await ensure_demo_content(session, real_master)


@pytest.mark.asyncio
async def test_ensure_demo_content_works_on_demo_master(db_session):
    """Тест: ensure_demo_content работает на демо-мастере."""
    session = db_session
    
    # Создаём демо-мастера через seed_master (без реального мастера id=1)
    await seed_master(session)
    
    # Находим демо-мастера (может быть id=1 или DEMO_MASTER_ID)
    result = await session.execute(select(Master).where(Master.is_demo == True))
    demo_master = result.scalar_one()
    
    # Проверяем, что ensure_demo_content работает (может вернуть True или False, но не ошибку)
    result = await ensure_demo_content(session, demo_master)
    assert result in [True, False]  # True если были изменения, False если уже всё было


@pytest.mark.asyncio
async def test_demo_master_has_rich_demo_data(db_session):
    """Тест: демо-мастер получает богатые тестовые данные."""
    session = db_session
    
    # Создаём демо-мастера через seed_master (без реального мастера id=1)
    await seed_master(session)
    
    # Находим демо-мастера (может быть id=1 или DEMO_MASTER_ID)
    result = await session.execute(select(Master).where(Master.is_demo == True))
    demo_master = result.scalar_one()
    
    # Запускаем ensure_demo_content
    await ensure_demo_content(session, demo_master)
    
    # Проверяем, что у демо-мастера есть услуги
    from backend.database import Service
    result = await session.execute(select(Service).where(Service.master_id == demo_master.id))
    services = result.scalars().all()
    assert len(services) >= 3
    assert any(s.name == "💇 Стрижка" for s in services)
    
    # Проверяем, что у демо-мастера есть записи на открытый период
    from backend.database import Booking
    result = await session.execute(
        select(Booking).where(Booking.master_id == demo_master.id)
    )
    bookings = result.scalars().all()
    assert len(bookings) > 0
    
    # Проверяем расписание
    assert demo_master.schedule_json.get("booking_days") == 90
