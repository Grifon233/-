"""Background runner for the (long) warm-up operations.

Warm-up cycles do real Telegram work with human-like pauses, so a single
"warm up everything" run can take *minutes* (account-to-account
conversations alone sleep 8-25s between messages and 20-60s between
pairs). Running that synchronously inside the HTTP request made the
browser hit its 30s axios timeout ("timeout of 30000ms exceeded") even
though the server kept working.

This module runs the work as a background asyncio task and exposes a
tiny in-memory job state the frontend can poll. Only ONE warm-up job
runs at a time (they all touch the same accounts/proxies), so a second
request while one is running is rejected with ``already_running``.

State is intentionally in-memory: warm-up is an operator-triggered,
best-effort action, and losing the last summary on a server restart is
harmless. If we ever need durability we'd move this to the DB.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


# Single global job slot. ``running`` guards against concurrent runs.
_state: Dict[str, Any] = {
    "running": False,
    "kind": None,           # 'all' | 'selected' | 'conversations'
    "started_at": None,
    "finished_at": None,
    "summary": "",          # human-readable, set when finished
    "error": None,
    "results": None,        # raw results (for debugging / future use)
}
# Strong reference so the background task isn't garbage-collected mid-run.
_task: Optional[asyncio.Task] = None


def get_state() -> Dict[str, Any]:
    """Public snapshot for the status endpoint."""
    return {k: _state[k] for k in ("running", "kind", "started_at", "finished_at", "summary", "error")}


def is_running() -> bool:
    return bool(_state["running"])


def _summarize(kind: str, results: List[Dict]) -> str:
    """Build a short Russian report from raw warm-up results."""
    # Per-account warm-up items carry a ``status``; the conversation step
    # is a single dict with ``type == 'account_conversations'``.
    convo = next((r for r in results if r.get("type") == "account_conversations"), None)
    per_account = [r for r in results if r.get("type") != "account_conversations"]
    completed = sum(1 for r in per_account if r.get("status") == "completed")
    failed = sum(1 for r in per_account if r.get("status") and r.get("status") != "completed")

    parts: List[str] = []
    if per_account:
        parts.append(f"Прогрев аккаунтов: выполнено {completed}, не выполнено {failed}")
    if convo is not None:
        if convo.get("status") == "completed":
            parts.append(
                f"Беседы между аккаунтами: пар {convo.get('pairs', 0)}, "
                f"отправлено сообщений {convo.get('messages_sent', 0)}"
            )
        else:
            parts.append(f"Беседы: пропущены ({convo.get('reason', 'нет данных')})")
    if not parts:
        parts.append("Подходящих аккаунтов не нашлось (нужны сессия, прокси, а для бесед — username).")
    return ". ".join(parts) + "."


async def _run_all(project_id: int) -> List[Dict]:
    from app.tasks.warmup import run_all_accounts_warmup
    async with SessionLocal() as db:
        return await run_all_accounts_warmup(db, project_id=project_id)


async def _run_selected(project_id: int, account_ids: List[int]) -> List[Dict]:
    from app.tasks.warmup import run_account_warmup
    from app.services import account_service
    results: List[Dict] = []
    async with SessionLocal() as db:
        for account_id in account_ids:
            account = await account_service.get_account(db, account_id, project_id=project_id)
            if not account:
                results.append({"account_id": account_id, "status": "error", "message": "not_found"})
                continue
            result = await run_account_warmup(db, account)
            results.append({"account_id": account_id, **(result or {})})
    return results


async def _run_conversations(project_id: int) -> List[Dict]:
    from app.services.warmup_conversations import run_warmup_conversations
    import random
    convo = await run_warmup_conversations(project_id=project_id, round_index=random.randint(0, 11))
    return [{"type": "account_conversations", **convo}]


async def _execute(kind: str, coro) -> None:
    """Wrap a warm-up coroutine: run it, record the summary, clear running."""
    try:
        results = await coro
        _state["results"] = results
        _state["summary"] = _summarize(kind, results or [])
        _state["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("warm-up job (%s) failed", kind)
        _state["error"] = str(exc)[:300]
        _state["summary"] = f"Прогрев завершился с ошибкой: {str(exc)[:200]}"
    finally:
        _state["running"] = False
        _state["finished_at"] = datetime.utcnow().isoformat()


def start(kind: str, project_id: int, account_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """Kick off a warm-up job in the background. Returns immediately.

    If a job is already running, returns ``{"status": "already_running"}``
    so the caller can tell the operator to wait.
    """
    global _task
    if _state["running"]:
        return {"status": "already_running", **get_state()}

    if kind == "all":
        coro = _run_all(project_id)
    elif kind == "selected":
        coro = _run_selected(project_id, account_ids or [])
    elif kind == "conversations":
        coro = _run_conversations(project_id)
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown warm-up kind: {kind}")

    _state.update(
        running=True,
        kind=kind,
        started_at=datetime.utcnow().isoformat(),
        finished_at=None,
        summary="",
        error=None,
        results=None,
    )
    _task = asyncio.create_task(_execute(kind, coro))
    return {"status": "started", **get_state()}
