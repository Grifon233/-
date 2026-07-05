from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from app.core.config import settings
from app.db import base as _models  # noqa: F401 - register all ORM mappings for workers

# SQLite doesn't support connection pooling like PostgreSQL
engine_kwargs = {
    "echo": False,
    "future": True,
}

if settings.USE_SQLITE:
    # SQLite: use NullPool for proper async behavior
    engine_kwargs["poolclass"] = NullPool
else:
    # PostgreSQL: use connection pooling
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    **engine_kwargs
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

async def get_db() -> AsyncSession: # type: ignore
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
