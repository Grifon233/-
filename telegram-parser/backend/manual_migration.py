import asyncio
from app.db.session import SessionLocal
from sqlalchemy import text

async def f():
    async with SessionLocal() as db:
        try:
            await db.execute(text('ALTER TABLE accounts ADD COLUMN gender VARCHAR'))
            await db.commit()
            print('Success')
        except Exception as e:
            print(f'Error: {e}')

if __name__ == "__main__":
    asyncio.run(f())
