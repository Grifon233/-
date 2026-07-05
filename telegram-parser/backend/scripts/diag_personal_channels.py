"""Read-only: show templates and what is actually in each account's channel."""
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.personal_channel_template import PersonalChannelTemplate
from app.services.telegram_service import telegram_service

ACCOUNTS = [10, 11]


async def main():
    async with SessionLocal() as db:
        print("=== TEMPLATES ===")
        tpls = (await db.execute(
            select(PersonalChannelTemplate).options(selectinload(PersonalChannelTemplate.posts))
        )).scalars().all()
        for t in tpls:
            print(f"template #{t.id} name={t.name!r} title={t.channel_title!r} "
                  f"avatar_mode={t.channel_avatar_mode} avatar_path={bool(t.channel_avatar_path)} posts={len(t.posts)}")
            for p in sorted(t.posts, key=lambda x: x.position):
                print(f"    pos={p.position} img={bool(p.image_path)} text={ (p.text or '')[:60]!r}")

        for aid in ACCOUNTS:
            acc = (await db.execute(
                select(Account).options(selectinload(Account.proxy)).where(Account.id == aid)
            )).scalar_one_or_none()
            if not acc:
                continue
            print(f"\n=== ACCOUNT #{aid} {acc.phone_number} pchan={acc.personal_channel_id} "
                  f"user={acc.personal_channel_username} ===")
            if not acc.personal_channel_id:
                print("  no personal channel"); continue
            try:
                from app.services.profile_service import _ensure_known_chat
                client = await asyncio.wait_for(telegram_service.get_client(acc), timeout=60)
                await _ensure_known_chat(client, acc.personal_channel_id)
                msgs = []
                async for m in client.get_chat_history(acc.personal_channel_id, limit=50):
                    txt = (m.text or m.caption or "").replace("\n", " ")
                    msgs.append((m.id, bool(m.photo), txt[:70]))
                print(f"  messages in channel (newest first): {len(msgs)}")
                for mid, has_photo, txt in msgs:
                    print(f"    msg {mid} photo={has_photo} {txt!r}")
            except Exception as e:
                print("  READ FAILED:", repr(e))


if __name__ == "__main__":
    asyncio.run(main())
