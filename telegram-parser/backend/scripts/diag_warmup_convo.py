"""Dry-run diagnostic for warmup conversations.

Prints which accounts are eligible (status, session, proxy, public
username, past newborn window) and which pairs would form — WITHOUT
sending any message. Lets us confirm the live run before doing it.
"""
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.account import Account, AccountStatus
from app.core.safety_guidelines import effective_account_age_days, phase_for_age_days
from app.services.warmup_conversations import _rotate_pairs

PROJECT_ID = 1


async def main():
    async with SessionLocal() as db:
        accounts = (
            await db.execute(
                select(Account)
                .options(selectinload(Account.proxy))
                .where(Account.project_id == PROJECT_ID)
            )
        ).scalars().all()

    print(f"Всего аккаунтов в проекте {PROJECT_ID}: {len(accounts)}\n")
    eligible = []
    for a in accounts:
        age = effective_account_age_days(a)
        mult = phase_for_age_days(age).multiplier
        has_sess = bool(a.session_string)
        ok = (
            a.status in (AccountStatus.WARMING, AccountStatus.PRODUCTION)
            and has_sess
            and a.proxy_id
            and a.username
            and mult > 0
        )
        if ok:
            eligible.append(a)
        reason = []
        if a.status not in (AccountStatus.WARMING, AccountStatus.PRODUCTION):
            reason.append(f"статус={a.status}")
        if not has_sess:
            reason.append("нет сессии")
        if not a.proxy_id:
            reason.append("нет прокси")
        if not a.username:
            reason.append("нет username")
        if mult <= 0:
            reason.append(f"newborn(age={age})")
        mark = "OK " if ok else "X  "
        print(f"{mark} id={a.id} {a.phone_number} статус={a.status} "
              f"@{a.username or '—'} прокси={a.proxy_id or '—'} возраст={age}д "
              f"{'| ' + ', '.join(reason) if reason else ''}")

    print(f"\nПодходящих аккаунтов: {len(eligible)}")
    if len(eligible) >= 2:
        pairs = _rotate_pairs(eligible, 0)
        print(f"Пар в раунде 0: {len(pairs)}")
        for x, y in pairs:
            print(f"  {x.phone_number} (@{x.username}) <-> {y.phone_number} (@{y.username})")
    else:
        print("Недостаточно для бесед (нужно >= 2).")


if __name__ == "__main__":
    asyncio.run(main())
