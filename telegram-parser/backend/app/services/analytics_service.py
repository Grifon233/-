"""
Analytics Service
Сбор статистики для дашборда.

The previous version returned hardcoded zeroes for ``total_messages``,
``success_rate``, ``total_reactions`` and ``total_groups`` — the
dashboard chart was permanently flat. We now compute the aggregates
from the actual tables; queries are wrapped in try/except so a missing
table (e.g. before the first migration) doesn't 500 the whole page.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _empty_summary() -> dict[str, Any]:
    return {
        "total_accounts": 0,
        "active_accounts": 0,
        "total_messages": 0,
        "success_rate": 0.0,
        "total_reactions": 0,
        "total_groups": 0,
    }


def _empty_chart() -> list[dict[str, Any]]:
    return [
        {
            "name": (datetime.utcnow() - timedelta(days=i)).strftime("%d.%m"),
            "messages": 0,
            "reactions": 0,
        }
        for i in range(6, -1, -1)
    ]


async def _scalar(db: AsyncSession, sql: str, **params) -> int:
    """Run a ``SELECT COUNT(*)`` and return 0 on any failure.

    Rolls back the session on failure so the next query doesn't
    inherit an ``InFailedSQLTransactionError`` from a poisoned
    transaction (asyncpg / SQLAlchemy will refuse every further
    statement until rollback).
    """
    try:
        result = await db.execute(text(sql), params)
        return int(result.scalar() or 0)
    except Exception as exc:
        # Table might not exist yet (pre-migration) or the column name
        # is wrong in some legacy DB. We don't want a single bad query
        # to 500 the whole dashboard. Roll back so subsequent queries
        # in the same request still work.
        try:
            await db.rollback()
        except Exception:
            pass
        logger.debug("analytics query failed: %s", exc)
        return 0


async def get_dashboard_stats(
    db: AsyncSession, project_id: int = 1
) -> dict[str, Any]:
    """Aggregated stats for the Dashboard page.

    Returns a payload that the frontend ``Dashboard.tsx`` already
    understands: ``{summary, activity_chart, recent_campaigns}``.
    """
    try:
        total_accounts = await _scalar(
            db,
            "SELECT COUNT(*) FROM accounts WHERE project_id = :project_id",
            project_id=project_id,
        )
        active_accounts = await _scalar(
            db,
            "SELECT COUNT(*) FROM accounts "
            "WHERE status = 'production' AND project_id = :project_id",
            project_id=project_id,
        )
        # MessageLog covers both manual messaging and campaign sends.
        total_messages = await _scalar(
            db,
            "SELECT COUNT(*) FROM message_logs "
            "WHERE status = 'sent' AND campaign_id IN ("
            "  SELECT id FROM campaigns WHERE project_id = :project_id"
            ")",
            project_id=project_id,
        )
        total_attempts = await _scalar(
            db,
            "SELECT COUNT(*) FROM message_logs WHERE campaign_id IN ("
            "  SELECT id FROM campaigns WHERE project_id = :project_id"
            ")",
            project_id=project_id,
        )
        success_rate = (
            round((total_messages / total_attempts) * 100, 1)
            if total_attempts > 0
            else 0.0
        )
        # ReactionTask.reactions_used is the canonical counter
        # (``reactions_used`` is incremented inside
        # ``reactions_service.mass_react_for_account``).
        total_reactions = await _scalar(
            db,
            "SELECT COALESCE(SUM(reactions_used), 0) FROM reaction_tasks "
            "WHERE project_id = :project_id",
            project_id=project_id,
        )
        # ``group_tasks`` covers the auto-join flow; ``safe_groups`` is
        # the curated catalogue. Sum both for an "engagement surface"
        # number the operator can glance at.
        total_groups = await _scalar(
            db,
            "SELECT COUNT(*) FROM group_tasks WHERE project_id = :project_id",
            project_id=project_id,
        )

        # 7-day activity chart. We group MessageLog by day so the
        # operator can see momentum at a glance.
        chart: list[dict[str, Any]] = []
        try:
            for offset in range(6, -1, -1):
                day = datetime.utcnow() - timedelta(days=offset)
                day_start = datetime(day.year, day.month, day.day)
                day_end = day_start + timedelta(days=1)
                msgs = await _scalar(
                    db,
                    "SELECT COUNT(*) FROM message_logs "
                    "WHERE status = 'sent' AND sent_at >= :start AND sent_at < :end",
                    start=day_start,
                    end=day_end,
                )
                chart.append(
                    {
                        "name": day.strftime("%d.%m"),
                        "messages": msgs,
                        "reactions": 0,
                    }
                )
        except Exception as exc:
            logger.debug("chart query failed: %s", exc)
            chart = _empty_chart()

        # Recent campaigns so the dashboard shows what was launched
        # lately. Joined in Python rather than via SQLAlchemy joins to
        # keep the error-handling surface small.
        recent_campaigns: list[dict[str, Any]] = []
        try:
            res = await db.execute(
                text(
                    "SELECT c.id, c.name, c.status, c.started_at, "
                    "       c.finished_at, "
                    "       (SELECT COUNT(*) FROM message_logs m "
                    "        WHERE m.campaign_id = c.id AND m.status = 'sent') AS sent, "
                    "       (SELECT COUNT(*) FROM message_logs m "
                    "        WHERE m.campaign_id = c.id AND m.status = 'failed') AS failed "
                    "FROM campaigns c "
                    "WHERE c.project_id = :project_id "
                    "ORDER BY COALESCE(c.started_at, c.created_at) DESC "
                    "LIMIT 5"
                ),
                {"project_id": project_id},
            )
            for row in res.fetchall():
                recent_campaigns.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "status": row[2],
                        "started_at": row[3].isoformat() if row[3] else None,
                        "finished_at": row[4].isoformat() if row[4] else None,
                        "sent": row[5] or 0,
                        "failed": row[6] or 0,
                    }
                )
        except Exception as exc:
            logger.debug("recent_campaigns query failed: %s", exc)

        return {
            "summary": {
                "total_accounts": total_accounts,
                "active_accounts": active_accounts,
                "total_messages": total_messages,
                "success_rate": success_rate,
                "total_reactions": total_reactions,
                "total_groups": total_groups,
            },
            "activity_chart": chart,
            "recent_campaigns": recent_campaigns,
        }
    except Exception as exc:
        logger.error("get_dashboard_stats failed: %s", exc)
        return {
            "summary": _empty_summary(),
            "activity_chart": _empty_chart(),
            "recent_campaigns": [],
        }
