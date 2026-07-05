"""Rewrite legacy plaintext secrets through encrypted SQLAlchemy columns."""

import asyncio

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.proxy import Proxy


async def main() -> None:
    async with SessionLocal() as db:
        accounts = (await db.execute(select(Account))).scalars().all()
        for account in accounts:
            await db.execute(
                update(Account)
                .where(Account.id == account.id)
                .values(api_hash=account.api_hash, session_string=account.session_string)
            )

        proxies = (await db.execute(select(Proxy))).scalars().all()
        for proxy in proxies:
            await db.execute(
                update(Proxy).where(Proxy.id == proxy.id).values(password=proxy.password)
            )

        await db.commit()
        print(f"Re-encrypted {len(accounts)} accounts and {len(proxies)} proxies")


if __name__ == "__main__":
    asyncio.run(main())
