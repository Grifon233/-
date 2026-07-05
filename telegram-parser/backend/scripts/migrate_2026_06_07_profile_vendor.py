import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB = "postgresql+asyncpg://postgres:oFZ_ULY64MeJ4rm1SIHGMhUaLzsYSJXSKaiDDkhGU10@localhost:5432/tgcomb"

STMTS = [
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS first_name VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_name VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS bio VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS username VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avatar_path VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS gender VARCHAR(16) NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS personal_channel_id INTEGER",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS personal_channel_username VARCHAR",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS profile_cache JSONB",
    "CREATE INDEX IF NOT EXISTS ix_accounts_username ON accounts(username)",
    "CREATE INDEX IF NOT EXISTS ix_accounts_status_sex ON accounts(status, gender)",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual'",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS vendor_name VARCHAR",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS vendor_proxy_id VARCHAR",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS country VARCHAR",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP",
    "ALTER TABLE proxies ADD COLUMN IF NOT EXISTS note VARCHAR",
]

async def main():
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        for s in STMTS:
            try:
                await conn.execute(text(s))
            except Exception as e:
                print(f"ERR {s[:60]}: {e}")
        # Show the resulting schema
        rows = (await conn.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'accounts' AND column_name IN
                ('first_name','last_name','bio','username','avatar_path','gender','personal_channel_id','personal_channel_username','profile_cache')
            ORDER BY column_name
        """)))
        print("=== accounts new columns ===")
        for r in rows:
            print(f"  {r.column_name:32s} {r.data_type}")
        rows = (await conn.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'proxies' AND column_name IN
                ('source','vendor_name','vendor_proxy_id','country','expires_at','note')
            ORDER BY column_name
        """)))
        print("=== proxies new columns ===")
        for r in rows:
            print(f"  {r.column_name:32s} {r.data_type}")
    await eng.dispose()

asyncio.run(main())
