"""LIVE warmup conversation run (sends real DMs between own accounts).

Runs round 0 with at most 1 pair through the proxy + rate limiter and
prints a detailed report. Authorized by the operator.
"""
import asyncio
import json
from app.services.warmup_conversations import run_warmup_conversations


async def main():
    res = await run_warmup_conversations(project_id=1, round_index=0, max_pairs=1)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
