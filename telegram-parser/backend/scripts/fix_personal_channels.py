"""Rebuild the personal channels of accounts that already have one so they
match template #1 exactly: no duplicates, profile avatar, correct order.
"""
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.personal_channel_template import PersonalChannelTemplate
from app.services import profile_service

TEMPLATE_ID = 1
ACCOUNT_IDS = [11, 10]   # 11 first (smaller), then 10


async def main():
    async with SessionLocal() as db:
        template = (await db.execute(
            select(PersonalChannelTemplate)
            .options(selectinload(PersonalChannelTemplate.posts))
            .where(PersonalChannelTemplate.id == TEMPLATE_ID)
        )).scalar_one()
        print(f"template #{template.id} {template.name!r} posts={len(template.posts)}")

        for aid in ACCOUNT_IDS:
            acc = (await db.execute(
                select(Account).options(selectinload(Account.proxy)).where(Account.id == aid)
            )).scalar_one()
            print(f"\n--- rebuilding account #{aid} {acc.phone_number} "
                  f"(channel {acc.personal_channel_id}) ---")
            try:
                res = await profile_service.rebuild_personal_channel_from_template(
                    db, acc, template, avatar="profile",
                )
                acc.personal_channel_template_id = template.id
                await db.commit()
                print("  OK:", res)
            except Exception as e:
                await db.rollback()
                print("  FAILED:", repr(e))


if __name__ == "__main__":
    asyncio.run(main())
