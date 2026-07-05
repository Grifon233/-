import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB = "postgresql+asyncpg://postgres:oFZ_ULY64MeJ4rm1SIHGMhUaLzsYSJXSKaiDDkhGU10@localhost:5432/tgcomb"

async def main():
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        r = await conn.execute(text("UPDATE accounts SET gender = 'unknown' WHERE gender IS NULL"))
        print(f"Backfilled {r.rowcount} rows with gender=unknown")
        rows = (await conn.execute(text("SELECT id, phone_number, gender, first_name, last_name, username, bio, personal_channel_id FROM accounts ORDER BY id"))).all()
        for row in rows:
            print(f"  #{row.id} {row.phone_number} gender={row.gender} name={row.first_name} {row.last_name} user={row.username} bio_len={len(row.bio) if row.bio else 0} ch={row.personal_channel_id}")
    await eng.dispose()

asyncio.run(main())
