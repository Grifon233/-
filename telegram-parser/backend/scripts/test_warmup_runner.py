"""Verify the background warm-up job machinery WITHOUT real Telegram work.

We monkeypatch the heavy coroutine with a fast fake, then exercise:
  - start() returns 'started' immediately
  - get_state() reports running=True while the fake sleeps
  - a second start() while running -> 'already_running'
  - after completion -> running=False + a human-readable summary
"""
import asyncio
from app.services import warmup_runner


async def fake_all(project_id):
    # Pretend to do a couple of accounts + a conversation step.
    await asyncio.sleep(1.0)
    return [
        {"account_id": 1, "status": "completed"},
        {"account_id": 2, "status": "failed", "error": "no proxy"},
        {"type": "account_conversations", "status": "completed", "pairs": 6, "messages_sent": 23},
    ]


async def main():
    warmup_runner._run_all = fake_all  # monkeypatch

    r1 = warmup_runner.start("all", project_id=1)
    print("1) start ->", r1["status"])

    await asyncio.sleep(0.2)
    print("2) state while running ->", warmup_runner.get_state()["running"])

    r2 = warmup_runner.start("all", project_id=1)
    print("3) second start while running ->", r2["status"])

    # wait for completion
    for _ in range(40):
        await asyncio.sleep(0.2)
        if not warmup_runner.is_running():
            break

    st = warmup_runner.get_state()
    print("4) running after finish ->", st["running"])
    print("5) summary ->", st["summary"])
    print("6) error ->", st["error"])

    assert r1["status"] == "started"
    assert r2["status"] == "already_running"
    assert st["running"] is False
    assert "Беседы" in st["summary"]
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
