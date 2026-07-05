"""Read back the last messages between the two warmed-up accounts to
prove the conversation really landed (not just 'sent ok')."""
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models.account import Account
from app.services.telegram_service import telegram_service

A_ID = 9          # Daniil — we read his dialog
PARTNER = "ru24_ivan_fedorov28"  # Ivan's public username


async def main():
    async with SessionLocal() as db:
        acc = (
            await db.execute(
                select(Account).options(selectinload(Account.proxy)).where(Account.id == A_ID)
            )
        ).scalar_one()

    client = await telegram_service.get_client(acc)
    print(f"Читаю диалог аккаунта {acc.phone_number} (@{acc.username}) с @{PARTNER}:\n")
    msgs = []
    async for m in client.get_chat_history(PARTNER, limit=10):
        who = "Даниил(сам)" if m.outgoing else "Иван"
        msgs.append((m.id, who, (m.text or "").strip()))
    for mid, who, text in reversed(msgs):
        print(f"  [{mid}] {who}: {text}")
    print(f"\nВсего сообщений прочитано: {len(msgs)}")


if __name__ == "__main__":
    asyncio.run(main())
