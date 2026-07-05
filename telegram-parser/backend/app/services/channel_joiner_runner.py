"""In-memory runner for progressive channel-joining sessions.

Mirrors the pattern of warmup_runner.py: one job slot, background asyncio
task, status the frontend can poll.

The background scheduler in main.py calls start() every 2-4 hours (Moscow
active hours).  The operator can also trigger a session manually via the
API (POST /join-pool/run).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "summary": "",
    "error": None,
    "results": None,
}
_task: Optional[asyncio.Task] = None


def get_state() -> Dict[str, Any]:
    return {k: _state[k] for k in ("running", "started_at", "finished_at", "summary", "error")}


def is_running() -> bool:
    return bool(_state["running"])


def _build_summary(results: List[Dict]) -> str:
    if not results:
        return "Нет аккаунтов для вступления."
    joined_total = sum(r.get("joined", 0) for r in results)
    skipped = sum(1 for r in results if r.get("skip_reason"))
    active = sum(1 for r in results if r.get("joined", 0) > 0)
    return (
        f"Сессия завершена: {active} аккаунт(ов) вступили в каналы, "
        f"всего вступлений {joined_total}, пропущено аккаунтов {skipped}."
    )


async def _execute(project_id: int | None) -> None:
    from app.services.channel_joiner_service import run_all_join_sessions
    try:
        results = await run_all_join_sessions(project_id)
        _state["results"] = results
        _state["summary"] = _build_summary(results or [])
        _state["error"] = None
    except Exception as exc:
        logger.exception("channel_joiner job failed")
        _state["error"] = str(exc)[:300]
        _state["summary"] = f"Ошибка: {str(exc)[:200]}"
    finally:
        _state["running"] = False
        _state["finished_at"] = datetime.utcnow().isoformat()


def start(project_id: int | None = None) -> Dict[str, Any]:
    """Kick off a join session in the background.  Returns immediately.

    ``project_id=None`` covers every project's eligible accounts (used by the
    background scheduler); a concrete id scopes it (manual API trigger).
    """
    global _task
    if _state["running"]:
        return {"status": "already_running", **get_state()}

    _state.update(
        running=True,
        started_at=datetime.utcnow().isoformat(),
        finished_at=None,
        summary="",
        error=None,
        results=None,
    )
    _task = asyncio.create_task(_execute(project_id))
    return {"status": "started", **get_state()}
