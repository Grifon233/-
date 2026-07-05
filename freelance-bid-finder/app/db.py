from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.config import DB_PATH
from app.models import Lead
from app.utils import now_iso


LOCK = threading.RLock()


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    with LOCK, _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                budget TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                raw_published TEXT NOT NULL DEFAULT '',
                matched_keywords TEXT NOT NULL DEFAULT '[]',
                score INTEGER NOT NULL DEFAULT 0,
                is_read INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                hidden_at TEXT,
                last_action TEXT NOT NULL DEFAULT '',
                last_action_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(source, source_id)
            );

            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL,
                total_found INTEGER NOT NULL DEFAULT 0,
                matched_found INTEGER NOT NULL DEFAULT 0,
                new_found INTEGER NOT NULL DEFAULT 0,
                errors TEXT NOT NULL DEFAULT '[]'
            );
            """
        )
        _ensure_column(connection, "leads", "hidden_at", "TEXT")
        _ensure_column(connection, "leads", "last_action", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "leads", "last_action_at", "TEXT")
        _ensure_column(connection, "scans", "closed_found", "INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            UPDATE leads
            SET last_action = 'hide',
                last_action_at = COALESCE(hidden_at, last_seen_at),
                hidden_at = COALESCE(hidden_at, last_seen_at)
            WHERE is_hidden = 1
              AND COALESCE(last_action, '') = ''
            """
        )
        connection.commit()


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upsert_leads(leads: list[Lead]) -> list[int]:
    new_ids: list[int] = []
    timestamp = now_iso()

    with LOCK, _connect() as connection:
        for lead in leads:
            payload = {
                "source": lead.source,
                "source_id": lead.source_id,
                "title": lead.title,
                "url": lead.url,
                "description": lead.description,
                "budget": lead.budget,
                "category": lead.category,
                "published_at": lead.published_at,
                "raw_published": lead.raw_published,
                "matched_keywords": json.dumps(
                    lead.matched_keywords,
                    ensure_ascii=False,
                ),
                "score": lead.score,
                "last_seen_at": timestamp,
            }
            existing = connection.execute(
                "SELECT id FROM leads WHERE source = ? AND source_id = ?",
                (lead.source, lead.source_id),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE leads
                    SET title = :title,
                        url = :url,
                        description = :description,
                        budget = :budget,
                        category = :category,
                        published_at = :published_at,
                        raw_published = :raw_published,
                        matched_keywords = :matched_keywords,
                        score = :score,
                        last_seen_at = :last_seen_at
                    WHERE source = :source AND source_id = :source_id
                    """,
                    payload,
                )
                continue

            payload["first_seen_at"] = timestamp
            cursor = connection.execute(
                """
                INSERT INTO leads (
                    source, source_id, title, url, description, budget, category,
                    published_at, raw_published, matched_keywords, score,
                    first_seen_at, last_seen_at
                )
                VALUES (
                    :source, :source_id, :title, :url, :description, :budget,
                    :category, :published_at, :raw_published, :matched_keywords,
                    :score, :first_seen_at, :last_seen_at
                )
                """,
                payload,
            )
            new_ids.append(int(cursor.lastrowid))
        connection.commit()

    return new_ids


def add_scan_result(result: dict[str, Any]) -> None:
    with LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO scans (
                started_at, finished_at, status, total_found, matched_found,
                new_found, closed_found, errors
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["started_at"],
                result["finished_at"],
                result["status"],
                result["total_found"],
                result["matched_found"],
                result["new_found"],
                result.get("closed_found", 0),
                json.dumps(result["errors"], ensure_ascii=False),
            ),
        )
        connection.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["matched_keywords"] = json.loads(data["matched_keywords"] or "[]")
    data["is_read"] = bool(data["is_read"])
    data["is_hidden"] = bool(data["is_hidden"])
    return data


def list_leads(
    source: str | None = None,
    unread_only: bool = False,
    query: str | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    where = ["is_hidden = 0"]
    values: list[Any] = []

    if source:
        where.append("source = ?")
        values.append(source)
    if unread_only:
        where.append("is_read = 0")
    if query:
        where.append("(title LIKE ? OR description LIKE ? OR category LIKE ?)")
        like = f"%{query}%"
        values.extend([like, like, like])

    sql = f"""
        SELECT *
        FROM leads
        WHERE {' AND '.join(where)}
        ORDER BY
            is_read ASC,
            COALESCE(published_at, first_seen_at) DESC,
            id DESC
        LIMIT ?
    """
    values.append(limit)

    with LOCK, _connect() as connection:
        return [_row_to_dict(row) for row in connection.execute(sql, values).fetchall()]


def list_hidden_leads(limit: int = 100) -> list[dict[str, Any]]:
    with LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM leads
            WHERE is_hidden = 1
            ORDER BY COALESCE(hidden_at, last_action_at, last_seen_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_action_leads(limit: int = 150) -> list[dict[str, Any]]:
    with LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM leads
            WHERE last_action IN ('hide', 'read', 'unread', 'restore', 'closed')
            ORDER BY COALESCE(last_action_at, hidden_at, last_seen_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_visible_leads(limit: int = 250) -> list[dict[str, Any]]:
    with LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM leads
            WHERE is_hidden = 0
            ORDER BY COALESCE(last_seen_at, first_seen_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def mark_read(lead_id: int, is_read: bool = True) -> None:
    timestamp = now_iso()
    with LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE leads
            SET is_read = ?,
                last_action = ?,
                last_action_at = ?
            WHERE id = ?
            """,
            (
                1 if is_read else 0,
                "read" if is_read else "unread",
                timestamp,
                lead_id,
            ),
        )
        connection.commit()


def mark_all_read() -> None:
    with LOCK, _connect() as connection:
        connection.execute(
            "UPDATE leads SET is_read = 1 WHERE is_hidden = 0"
        )
        connection.commit()


def hide_lead(lead_id: int) -> None:
    timestamp = now_iso()
    with LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE leads
            SET is_hidden = 1,
                hidden_at = ?,
                last_action = 'hide',
                last_action_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, lead_id),
        )
        connection.commit()


def restore_lead(lead_id: int) -> None:
    timestamp = now_iso()
    with LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE leads
            SET is_hidden = 0,
                hidden_at = NULL,
                last_action = 'restore',
                last_action_at = ?
            WHERE id = ?
            """,
            (timestamp, lead_id),
        )
        connection.commit()


def close_lead(lead_id: int, reason: str = "") -> None:
    timestamp = now_iso()
    with LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE leads
            SET is_hidden = 1,
                hidden_at = ?,
                last_action = 'closed',
                last_action_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, lead_id),
        )
        connection.commit()


def get_stats() -> dict[str, Any]:
    with LOCK, _connect() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM leads WHERE is_hidden = 0"
        ).fetchone()[0]
        unread = connection.execute(
            "SELECT COUNT(*) FROM leads WHERE is_hidden = 0 AND is_read = 0"
        ).fetchone()[0]
        hidden = connection.execute(
            "SELECT COUNT(*) FROM leads WHERE is_hidden = 1"
        ).fetchone()[0]
        actions = connection.execute(
            """
            SELECT COUNT(*)
            FROM leads
            WHERE last_action IN ('hide', 'read', 'unread', 'restore', 'closed')
            """
        ).fetchone()[0]
        by_source = {
            row["source"]: row["count"]
            for row in connection.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM leads
                WHERE is_hidden = 0
                GROUP BY source
                """
            ).fetchall()
        }
        last_scan = connection.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "total": total,
        "unread": unread,
        "hidden": hidden,
        "actions": actions,
        "by_source": by_source,
        "last_scan": dict(last_scan) if last_scan else None,
    }
