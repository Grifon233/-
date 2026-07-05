"""Set the personal-channel link in the bio for accounts that have a channel,
then read the profile back to confirm the link is visible."""
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account
from app.services import profile_service
from app.services.telegram_service import telegram_service

ACCOUNT_IDS = [11, 10]


async def main():
    async with SessionLocal() as db:
        for aid in ACCOUNT_IDS:
            acc = (await db.execute(
                select(Account).options(selectinload(Account.proxy)).where(Account.id == aid)
            )).scalar_one()
            print(f"\n--- account #{aid} {acc.phone_number} channel=@{acc.personal_channel_username} ---")
            ok = await profile_service.set_channel_link_in_bio(db, acc)
            print(f"  set_channel_link_in_bio -> {ok}, bio now: {acc.bio!r}")
            # Read back from Telegram to confirm it's live on the profile.
            try:
                client = await telegram_service.get_client(acc)
                me = await client.get_me()
                full = await client.get_users(me.id)
                print(f"  LIVE profile bio: {getattr(full, 'bio', None)!r}")
            except Exception as e:
                print("  readback failed:", repr(e))


if __name__ == "__main__":
    asyncio.run(main())
