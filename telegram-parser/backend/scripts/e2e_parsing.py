"""LIVE E2E for parsing: keyword -> channels/groups (CHAT_SEARCH).

Creates a real parsing task, runs the actual parser (fresh code, through
the account proxy), and prints the task status + a sample of the CSV.
Read-only on Telegram (search + GetFullChannel), no posting.
"""
import asyncio
import csv

from sqlalchemy.future import select

from app.db.session import SessionLocal
from app.models.parsing import ParsingTask, ParsingType, ParsingStatus
from app.tasks.parsing import _run

ACCOUNT_ID = 9
KEYWORDS = "наращивание ресниц,маникюр"


async def main():
    async with SessionLocal() as db:
        task = ParsingTask(
            type=ParsingType.CHAT_SEARCH,
            status=ParsingStatus.PENDING,
            target=KEYWORDS,
            params={
                "limit": 40,
                "per_keyword_limit": 20,
                "only_with_discussion": False,
                "min_participants": 0,
                "chat_type": "all",
            },
            account_id=ACCOUNT_ID,
            project_id=1,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        tid = task.id
    print(f"created CHAT_SEARCH task #{tid}, keywords={KEYWORDS!r} account={ACCOUNT_ID}")
    print("running parser (rate-limited, a few minutes)...")
    await _run(tid)

    async with SessionLocal() as db:
        task = await db.get(ParsingTask, tid)
        print(f"\nTASK #{tid} status={task.status} result_count={task.result_count}")
        print(f"file_path={task.file_path}")
        print(f"params.last_error={ (task.params or {}).get('last_error') }")
        if task.file_path:
            import os
            if os.path.exists(task.file_path):
                with open(task.file_path, encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                print(f"\nCSV rows: {len(rows)}. Sample:")
                for r in rows[:12]:
                    print(f"  [{r.get('type')}] @{r.get('username')} | {r.get('title')} "
                          f"| participants={r.get('participants_count')} | discussion={r.get('has_discussion')}")
            else:
                print("CSV file missing on disk")


if __name__ == "__main__":
    asyncio.run(main())
