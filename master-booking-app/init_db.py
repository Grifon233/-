#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/root/master-booking')

from backend.database import Base, engine

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Database tables created')

asyncio.run(init_db())