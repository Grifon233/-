"""Continuous background warmup scheduler.

Runs warmup for all NEW/WARMING accounts on a randomized schedule so the
operator doesn't have to press "Прогрев" manually every time.

Settings are persisted to ``warmup_scheduler_settings.json`` in the backend
root — no DB migration required, losses on restart are harmless.

Behaviour
---------
* Checks every 60 s whether auto-warmup is enabled.
* When enabled, sleeps a random interval (interval_min..interval_max hours).
* On wake: checks Moscow active hours, applies a random skip chance, then
  calls ``warmup_runner.start("all", project_id)``.
* Designed to coexist with manual warmup presses — warmup_runner.start()
  already guards against concurrent runs (returns "already_running").
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SETTINGS_FILE = "warmup_scheduler_settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "interval_min_hours": 4,
    "interval_max_hours": 8,
    "active_hours_start": 8,   # Moscow time (UTC+3)
    "active_hours_end": 23,
    "skip_chance": 0.15,       # 15% human-like skip
    "project_id": 1,
}

_settings: Dict[str, Any] = {}
_task: Optional[asyncio.Task] = None
_last_run_at: Optional[str] = None
_next_run_at: Optional[str] = None


def _load() -> Dict[str, Any]:
    global _settings
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                _settings = {**DEFAULT_SETTINGS, **json.load(f)}
        else:
            _settings = dict(DEFAULT_SETTINGS)
    except Exception as exc:
        logger.warning("warmup_scheduler: could not load settings: %s", exc)
        _settings = dict(DEFAULT_SETTINGS)
    return _settings


def _save() -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_settings, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("warmup_scheduler: could not save settings: %s", exc)


def get_settings() -> Dict[str, Any]:
    if not _settings:
        _load()
    return dict(_settings)


def update_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    _load()
    for k, v in patch.items():
        if k in DEFAULT_SETTINGS:
            _settings[k] = v
    _save()
    return dict(_settings)


def _moscow_hour() -> int:
    return (datetime.now(timezone.utc).hour + 3) % 24


def _is_active() -> bool:
    h = _moscow_hour()
    start = int(_settings.get("active_hours_start", 8))
    end = int(_settings.get("active_hours_end", 23))
    return start <= h < end


async def _loop() -> None:
    global _last_run_at, _next_run_at

    while True:
        _load()

        if not _settings.get("enabled"):
            await asyncio.sleep(60)
            continue

        min_h = float(_settings.get("interval_min_hours", 4))
        max_h = float(_settings.get("interval_max_hours", 8))
        wait_secs = random.uniform(min_h * 3600, max_h * 3600)

        wake_at = datetime.utcnow()
        wake_at = wake_at.replace(
            second=int(wake_at.second + wait_secs) % 60,
        )
        _next_run_at = datetime.utcnow().isoformat()

        logger.info(
            "warmup_scheduler: next run in %.1f h", wait_secs / 3600
        )
        await asyncio.sleep(wait_secs)

        _load()
        if not _settings.get("enabled"):
            continue

        if not _is_active():
            logger.info(
                "warmup_scheduler: outside active hours (%s МСК), skipping",
                _moscow_hour(),
            )
            continue

        if random.random() < float(_settings.get("skip_chance", 0.15)):
            logger.info("warmup_scheduler: random skip (human simulation)")
            continue

        try:
            from app.services import warmup_runner

            project_id = int(_settings.get("project_id", 1))
            logger.info("warmup_scheduler: triggering warmup for project %s", project_id)
            result = warmup_runner.start("all", project_id)
            _last_run_at = datetime.utcnow().isoformat()
            logger.info("warmup_scheduler: started — %s", result.get("status"))
        except Exception as exc:
            logger.error("warmup_scheduler: run failed: %s", exc)


def start_scheduler() -> None:
    """Called once on FastAPI startup inside the running event loop."""
    global _task
    _load()
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        logger.info(
            "warmup_scheduler: started (enabled=%s)", _settings.get("enabled")
        )


def stop_scheduler() -> None:
    """Called on FastAPI shutdown."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("warmup_scheduler: stopped")


def get_status() -> Dict[str, Any]:
    _load()
    return {
        "enabled": bool(_settings.get("enabled", False)),
        "interval_min_hours": _settings.get("interval_min_hours", 4),
        "interval_max_hours": _settings.get("interval_max_hours", 8),
        "active_hours_start": _settings.get("active_hours_start", 8),
        "active_hours_end": _settings.get("active_hours_end", 23),
        "skip_chance": _settings.get("skip_chance", 0.15),
        "project_id": _settings.get("project_id", 1),
        "scheduler_running": _task is not None and not _task.done(),
        "last_run_at": _last_run_at,
    }
