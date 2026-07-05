from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from app import db
from app.filters import evaluate_lead
from app.models import Lead
from app.sources import flru, freelanceru, kwork
from app.utils import now_iso


SourceFetcher = Callable[[dict], list[Lead]]


SOURCE_FETCHERS: dict[str, SourceFetcher] = {
    "kwork": kwork.fetch_leads,
    "fl_ru": flru.fetch_leads,
    "freelance_ru": freelanceru.fetch_leads,
}

STATUS_CHECKERS = {
    "kwork": kwork.closed_reason,
    "fl_ru": flru.closed_reason,
    "freelance_ru": freelanceru.closed_reason,
}


def _is_recent(lead: Lead, config: dict) -> bool:
    max_age_days = config.get("max_age_days")
    if not max_age_days or not lead.published_at:
        return True
    try:
        published_at = datetime.fromisoformat(lead.published_at.replace("Z", "+00:00"))
    except ValueError:
        return True

    threshold = datetime.now(timezone.utc).astimezone() - timedelta(
        days=float(max_age_days)
    )
    if published_at.tzinfo is None:
        threshold = threshold.replace(tzinfo=None)
    return published_at >= threshold


class ScannerService:
    def __init__(self, config: dict):
        self.config = config
        self._scan_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._active_thread: threading.Thread | None = None
        self._last_result: dict | None = None
        self._running = False
        self._next_scan_at: str | None = None

    def start(self, run_immediately: bool = True) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        if run_immediately:
            self.run_async()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="lead-monitor-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def run_async(self) -> bool:
        if self._active_thread and self._active_thread.is_alive():
            return False
        self._active_thread = threading.Thread(
            target=self.run_once,
            name="lead-monitor-scan",
            daemon=True,
        )
        self._active_thread.start()
        return True

    def run_once(self) -> dict:
        if not self._scan_lock.acquire(blocking=False):
            return {
                "status": "busy",
                "started_at": now_iso(),
                "finished_at": now_iso(),
                "total_found": 0,
                "matched_found": 0,
                "new_found": 0,
                "errors": ["Сканирование уже выполняется"],
            }

        self._running = True
        started_at = now_iso()
        total_found = 0
        matched_leads: list[Lead] = []
        errors: list[str] = []
        closed_found = 0

        try:
            for source_name, fetcher in SOURCE_FETCHERS.items():
                source_config = self.config["sources"].get(source_name, {})
                if not source_config.get("enabled", False):
                    continue
                try:
                    leads = fetcher(self.config)
                except Exception as exc:
                    errors.append(f"{source_name}: {exc}")
                    continue

                total_found += len(leads)
                for lead in leads:
                    evaluated = evaluate_lead(lead, self.config)
                    if (
                        evaluated.score >= int(self.config["min_score"])
                        and _is_recent(evaluated, self.config)
                    ):
                        matched_leads.append(evaluated)

            new_ids = db.upsert_leads(matched_leads)
            closed_found = self._hide_closed_leads(errors)
            result = {
                "status": "ok" if not errors else "partial",
                "started_at": started_at,
                "finished_at": now_iso(),
                "total_found": total_found,
                "matched_found": len(matched_leads),
                "new_found": len(new_ids),
                "closed_found": closed_found,
                "errors": errors,
            }
            db.add_scan_result(result)
            self._last_result = result
            self._next_scan_at = self._calculate_next_scan()
            return result
        finally:
            self._running = False
            self._scan_lock.release()

    def status(self) -> dict:
        return {
            "running": self._running,
            "last_result": self._last_result,
            "next_scan_at": self._next_scan_at,
            "interval_hours": self.config["scan_interval_hours"],
        }

    def _hide_closed_leads(self, errors: list[str]) -> int:
        limit = int(self.config.get("status_check_limit", 120))
        closed_count = 0
        for lead in db.list_visible_leads(limit=limit):
            checker = STATUS_CHECKERS.get(lead["source"])
            if not checker:
                continue
            try:
                reason = checker(lead["url"], self.config)
            except Exception as exc:
                errors.append(f"status {lead['source']}:{lead['source_id']}: {exc}")
                continue
            if reason:
                db.close_lead(int(lead["id"]), reason)
                closed_count += 1
        return closed_count

    def _scheduler_loop(self) -> None:
        interval = float(self.config["scan_interval_hours"]) * 60 * 60
        self._next_scan_at = self._calculate_next_scan()
        while not self._stop_event.wait(interval):
            self.run_once()

    def _calculate_next_scan(self) -> str:
        next_scan = datetime.now(timezone.utc).astimezone() + timedelta(
            hours=float(self.config["scan_interval_hours"])
        )
        return next_scan.isoformat(timespec="seconds")
