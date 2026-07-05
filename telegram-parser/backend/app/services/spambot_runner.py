"""Background @SpamBot check job.

Sends /start to @SpamBot from each eligible account, reads the response,
and stores the result in health_factors["spambot"].  Single-slot job —
only one run at a time.  Frontend polls GET /accounts/spambot-job.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "progress": "",
    "report": None,
    "total": 0,
    "done": 0,
}
_task: Optional[asyncio.Task] = None


def start(project_id: int) -> dict:
    global _task
    if _state["running"]:
        return {"status": "already_running", **get_state()}
    _state.update(
        running=True,
        started_at=datetime.utcnow().isoformat(),
        finished_at=None,
        progress="Запускаю проверку @SpamBot…",
        report=None,
        total=0,
        done=0,
    )
    _task = asyncio.create_task(_execute(project_id))
    return {"status": "started", **get_state()}


def get_state() -> dict:
    return dict(_state)


def is_running() -> bool:
    return bool(_state["running"])


async def _execute(project_id: int) -> None:
    try:
        await _run(project_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("spambot runner crashed: %s", exc)
        _state["report"] = f"Ошибка: {exc}"
    finally:
        _state["running"] = False
        _state["finished_at"] = datetime.utcnow().isoformat()


async def _run(project_id: int) -> None:
    from app.db.session import SessionLocal
    from app.models.account import Account as AccountModel
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with SessionLocal() as db:
        accounts = (
            await db.execute(
                select(AccountModel)
                .options(selectinload(AccountModel.proxy))
                .where(
                    AccountModel.project_id == project_id,
                    AccountModel.session_string.isnot(None),
                    AccountModel.proxy_id.isnot(None),
                )
            )
        ).scalars().all()

    _state["total"] = len(accounts)
    results: list[dict] = []

    for account in accounts:
        _state["progress"] = (
            f"@SpamBot: проверяю {account.phone_number} ({_state['done'] + 1}/{_state['total']})…"
        )
        row = await _check_one(account)
        results.append(row)
        _state["done"] += 1

    clean = sum(1 for r in results if r.get("spambot_status") == "clean")
    spam = sum(1 for r in results if r.get("spambot_status") == "spam")
    err = len(results) - clean - spam
    _state["report"] = (
        f"@SpamBot готово: чистых {clean}, ограничен {spam}, ошибок {err} из {len(results)}."
    )
    _state["progress"] = "Готово"


async def _check_one(account) -> dict:
    from app.db.session import SessionLocal
    from app.models.account import Account as AccountModel
    from app.services.telegram_service import telegram_service
    from sqlalchemy import select

    row: dict[str, Any] = {
        "account_id": account.id,
        "phone": account.phone_number,
        "spambot_status": "error",
    }
    try:
        client = await telegram_service.get_client(account)

        # Send /start to SpamBot — it always replies in seconds.
        await client.send_message("SpamBot", "/start")
        await asyncio.sleep(4)

        bot_text = ""
        async for msg in client.get_chat_history("SpamBot", limit=5):
            if msg.from_user and getattr(msg.from_user, "is_bot", False):
                bot_text = msg.text or msg.caption or ""
                break

        spambot = _parse_spambot_reply(bot_text)
        row["spambot_status"] = spambot["status"]
        if spambot.get("until"):
            row["until"] = spambot["until"]

        # Persist to health_factors (merge-safe).
        async with SessionLocal() as db:
            acc = (
                await db.execute(select(AccountModel).where(AccountModel.id == account.id))
            ).scalar_one_or_none()
            if acc:
                factors = dict(acc.health_factors or {})
                factors["spambot"] = spambot
                # SpamBot says clean → auto-clear PEER_FLOOD restriction
                if spambot["status"] == "clean":
                    restriction = factors.get("restriction")
                    if restriction and restriction.get("reason") == "PEER_FLOOD":
                        factors.pop("restriction", None)
                        row["restriction_cleared"] = True
                acc.health_factors = factors
                await db.commit()

    except Exception as exc:  # noqa: BLE001
        logger.warning("spambot check failed for %s: %s", account.id, exc)
        row["spambot_status"] = "error"
        row["error"] = str(exc)[:120]

    return row


def _parse_spambot_reply(text: str) -> dict:
    """Parse @SpamBot's reply and return a structured status dict."""
    result: dict[str, Any] = {
        "status": "unknown",
        "until": None,
        "text": text[:300] if text else "",
        "checked_at": datetime.utcnow().isoformat(),
    }

    if not text:
        result["status"] = "no_reply"
        return result

    low = text.lower()

    clean_phrases = ["no limits", "good news", "нет ограничений", "no ban", "not limited"]
    if any(p in low for p in clean_phrases):
        result["status"] = "clean"
        return result

    spam_phrases = ["limited", "restrict", "ограничен", "заблокирован", "spam", "your account was"]
    if any(p in low for p in spam_phrases):
        result["status"] = "spam"
        # Detect permanent ban.
        permanent_phrases = [
            "forever", "permanent", "indefinitely", "навсегда", "бессрочно",
            "will not be lifted", "cannot be lifted", "no expiry",
        ]
        result["permanent"] = any(p in low for p in permanent_phrases)
        # Try to extract the expiry date (several formats used by SpamBot).
        if not result["permanent"]:
            patterns = [
                r"\d{1,2}\s+\w+\s+\d{4}",    # "31 December 2024"
                r"\w+\s+\d{1,2},?\s+\d{4}",   # "December 31, 2024" or "Dec 31, 2024"
                r"\d{2}\.\d{2}\.\d{4}",        # "31.12.2024"
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    result["until"] = m.group(0)
                    break
        return result

    return result
