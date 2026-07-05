"""Test-suite config — adds the project root to ``sys.path`` and
exposes the FastAPI ``app`` package for import.

We do not want to require a running Postgres / Redis to run the
unit tests, so the conftest monkey-patches
:func:`app.db.session.get_db` to return an in-memory SQLite session.
"""
from __future__ import annotations

import os
import sys
import asyncio
import pathlib
from typing import AsyncGenerator

# Make ``app`` importable.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force SQLite for tests, regardless of the developer's .env.
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault("SQLITE_DB_PATH", ":memory:")
os.environ.setdefault("ENCRYPTION_KEY", "WFVAY3M3SU0ROoNBxa6D0R9G0QzY1C2tQOm1SU5FaW0=")
os.environ.setdefault("SECRET_KEY", "x" * 32)
os.environ.setdefault("ADMIN_API_TOKEN", "test-admin-token")
os.environ.setdefault("REDIS_PASSWORD", "test-redis")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base_class import Base
import app.models  # noqa: F401  (registers ORM models)


def pytest_collection_modifyitems(config, items):
    """Auto-mark async tests so we don't have to decorate each one."""
    for item in items:
        if asyncio.iscoroutinefunction(getattr(item, "function", None)):
            item.add_marker(pytest.mark.asyncio)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A fresh in-memory SQLite database per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
