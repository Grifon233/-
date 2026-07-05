#!/usr/bin/env python3
"""
Pytest fixtures for master-booking tests.
"""
import asyncio
import os
from typing import AsyncGenerator

# Подпись ссылок теперь fail-closed: без секрета сервер отклоняет запросы.
# Тестам нужен стабильный секрет, чтобы проверять подписанные ссылки.
os.environ.setdefault("AUTH_SIGNING_SECRET", "test-signing-secret")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base, get_db
from typing import AsyncGenerator

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
test_async_session_maker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fixture for async database session with clean database for each test."""
    # Drop all tables first to ensure clean state
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session = test_async_session_maker()
    async with session as s:
        yield s

    # Drop all tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Close all connections to avoid leaks
    await test_engine.dispose()


@pytest.fixture(scope="function")
def override_get_db(db_session: AsyncSession) -> None:
    """Override get_db dependency to use test session."""
    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Patch the dependency (if needed for FastAPI tests)
    import backend.database
    backend.database.get_db = _get_db_override


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession, override_get_db: None) -> AsyncGenerator:
    """FastAPI test client with clean DB and overridden get_db."""
    from fastapi.testclient import TestClient
    from backend.main import app

    # Override get_db dependency
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()