"""DRY-RUN diagnostic for neuro-commenting (no publishing).

Reads recent messages from the given sources with a real account,
applies the human-comment filter, and asks the AI for a draft —
WITHOUT posting anything to Telegram. Prints what it would do so we
can verify quality before any public post.
"""
import asyncio
import sys

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.telegram_source import TelegramSource
from app.services.telegram_service import telegram_service
from app.services.ai_provider_service import get_ai_client, get_provider_config
from app.tasks.commenting import (
    telegram_chat_target,
    collect_recent_messages,
    _is_human_comment,
    generate_comment_draft,
)
from app.models.comment_task import CommentTargetMode
from app.core.config import settings

ACCOUNT_ID = 9            # +8928500039
SOURCE_IDS = [476, 469]   # narashivanie_resnic_chat, modelsbrd
PROVIDER = "deepseek"
MODEL = "deepseek-v4-flash"


async def main():
    async with SessionLocal() as db:
        acc = (await db.execute(
            select(Account).options(selectinload(Account.proxy)).where(Account.id == ACCOUNT_ID)
        )).scalar_one_or_none()
        if not acc:
            print("NO ACCOUNT", ACCOUNT_ID); return
        print(f"account #{acc.id} {acc.phone_number} status={acc.status} proxy={acc.proxy_id} "
              f"personal_channel={acc.personal_channel_id} username={acc.personal_channel_username}")

        cfg = get_provider_config(PROVIDER)
        key = getattr(settings, cfg["key_setting"], None)
        print("AI provider:", PROVIDER, "key_set:", bool(key))
        ai = get_ai_client(PROVIDER)

        try:
            client = await asyncio.wait_for(telegram_service.get_client(acc), timeout=45)
        except Exception as e:
            print("CLIENT CONNECT FAILED:", repr(e)); return
        me = await client.get_me()
        print(f"connected as: id={me.id} name={me.first_name} username={me.username}")

        for sid in SOURCE_IDS:
            src = await db.get(TelegramSource, sid)
            if not src:
                print("no source", sid); continue
            target = telegram_chat_target(src)
            print("\n" + "=" * 70)
            print(f"SOURCE #{sid} {src.normalized_link} type={src.source_type} -> target={target!r}")
            try:
                raw = await collect_recent_messages(client, target, limit=60)
            except Exception as e:
                print("  READ FAILED:", repr(e)); continue
            print(f"  fetched {len(raw)} raw messages (newest first)")

            human = []
            dropped = []
            for m in raw:
                txt = (getattr(m, "text", None) or getattr(m, "caption", None) or "").strip()
                if _is_human_comment(m):
                    human.append(txt)
                else:
                    if txt:
                        dropped.append(txt[:60])
                if len(human) >= 5:
                    break
            print(f"  --- DROPPED (service/bot/ad/forward), first few: ---")
            for d in dropped[:6]:
                print("     x", repr(d))
            print(f"  --- KEPT human messages (newest first, max 5): ---")
            for h in human:
                print("     +", repr(h[:120]))

            if not human:
                print("  -> no human messages to base a comment on")
                continue

            ctx = "RECENT GROUP MESSAGES:\n" + "\n".join(f"- {m}" for m in reversed(human))
            draft = await generate_comment_draft(
                ai, ctx, src.normalized_link, MODEL, target_mode=CommentTargetMode.GROUP_CONTEXT
            )
            print("  >>> AI DRAFT:", repr(draft))

    print("\nDRY-RUN complete. Nothing was posted.")


if __name__ == "__main__":
    asyncio.run(main())
