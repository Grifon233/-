"""Export every account's DECRYPTED session + credentials to a JSON backup.

This is the strongest safety net before any risky change: even if the DB
or the Telegram library breaks, accounts can be fully re-created from this
file. The session_string is the same StringSession used by Pyrogram, so it
is portable across Pyrogram versions/forks.
"""
import asyncio
import json
import sys
from datetime import datetime

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account


async def main(out_path: str):
    async with SessionLocal() as db:
        accounts = (
            await db.execute(select(Account).options(selectinload(Account.proxy)))
        ).scalars().all()
        data = []
        for a in accounts:
            data.append({
                "id": a.id,
                "phone_number": a.phone_number,
                "api_id": a.api_id,
                "api_hash": a.api_hash,                 # decrypted by EncryptedString
                "session_string": a.session_string,     # decrypted by EncryptedString
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "folder": a.folder,
                "proxy_id": a.proxy_id,
                "personal_channel_id": a.personal_channel_id,
                "personal_channel_username": a.personal_channel_username,
                "personal_channel_template_id": getattr(a, "personal_channel_template_id", None),
                "first_name": a.first_name,
                "username": a.username,
                "proxy": None if not a.proxy else {
                    "scheme": a.proxy.scheme, "host": a.proxy.host, "port": a.proxy.port,
                    "username": a.proxy.username, "password": a.proxy.password,
                    "is_active": getattr(a.proxy, "is_active", None),
                },
            })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"exported_at": datetime.utcnow().isoformat(), "accounts": data}, f,
                  ensure_ascii=False, indent=2)
    print(f"backed up {len(data)} accounts -> {out_path}")
    for a in data:
        print(f"  #{a['id']} {a['phone_number']} session_len={len(a['session_string'] or '')} "
              f"proxy={a['proxy_id']} pchan={a['personal_channel_id']}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
