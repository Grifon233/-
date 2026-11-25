"""Хранилище активных отметок: SQLite в файле или в памяти."""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.config import settings
from app.schemas import Quote, Street
from app.services.cities import normalize_city
from app.services.street_names import street_key


def _street_id(city: str, street: str) -> str:
    return f"{city.casefold()}::{street_key(street)}"


class SightingsStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = RLock()
        if path != ":memory:":
            file = Path(path).expanduser().resolve()
            file.parent.mkdir(parents=True, exist_ok=True)
            path = str(file)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=3)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA secure_delete = ON")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS streets (
                id TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                street TEXT NOT NULL,
                geometry TEXT
            );
            CREATE INDEX IF NOT EXISTS streets_city ON streets (city, id);
            CREATE TABLE IF NOT EXISTS sightings (
                event_key TEXT UNIQUE,
                street_id TEXT NOT NULL REFERENCES streets (id),
                quote TEXT NOT NULL,
                observed_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sightings_street ON sightings (street_id, expires_at);
            CREATE INDEX IF NOT EXISTS sightings_expiry ON sightings (expires_at);
        """)
        self.purge_expired()

    def purge_expired(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sightings WHERE expires_at <= ?", (time.time(),))
            self._db.execute("""
                DELETE FROM streets
                WHERE NOT EXISTS (SELECT 1 FROM sightings WHERE street_id = streets.id)
            """)

    def find_event(self, event_key: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._db.execute("""
                SELECT st.city, st.street FROM sightings AS s
                JOIN streets AS st ON st.id = s.street_id
                WHERE s.event_key = ? AND s.expires_at > ?
            """, (event_key, time.time())).fetchone()
        return (row["city"], row["street"]) if row else None

    def add(
        self,
        city: str,
        street: str,
        quote: Quote,
        event_key: str,
        expires_at: float,
        geometry: dict | None = None,
    ) -> bool:
        """Не продлевает старую отметку и не записывает повторное событие."""
        sid = _street_id(city, street)
        with self._lock:
            now = time.time()
            if expires_at <= now:
                return False
            try:
                with self._db:
                    self._db.execute("""
                        DELETE FROM sightings WHERE event_key = ? AND expires_at <= ?
                    """, (event_key, now))
                    self._db.execute("""
                        INSERT INTO streets (id, city, street, geometry)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            geometry = CASE WHEN EXISTS (
                                SELECT 1 FROM sightings WHERE street_id = streets.id AND expires_at > ?
                            ) THEN COALESCE(streets.geometry, excluded.geometry)
                            ELSE excluded.geometry END,
                            street = CASE WHEN EXISTS (
                                SELECT 1 FROM sightings WHERE street_id = streets.id AND expires_at > ?
                            ) THEN streets.street ELSE excluded.street END
                    """, (sid, city, street, json.dumps(geometry) if geometry else None, now, now))
                    self._db.execute("""
                        INSERT INTO sightings (event_key, street_id, quote, observed_at, expires_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (event_key, sid, quote.model_dump_json(), quote.ts.timestamp(), expires_at))
            except sqlite3.IntegrityError as exc:
                if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    return False
                raise
        return True

    def get_geometry(self, city: str, street: str) -> dict | None:
        with self._lock:
            row = self._db.execute("""
                SELECT geometry FROM streets WHERE id = ? AND geometry IS NOT NULL
                AND EXISTS (SELECT 1 FROM sightings WHERE street_id = streets.id AND expires_at > ?)
            """, (_street_id(city, street), time.time())).fetchone()
        return json.loads(row["geometry"]) if row else None

    def _streets(self, city: str | None = None, sid: str | None = None) -> list[Street]:
        filters = ["s.expires_at > ?"]
        values: list[str | float] = [time.time()]
        if city is not None:
            filters.append("st.city = ?")
            values.append(city)
        if sid is not None:
            filters.append("st.id = ?")
            values.append(sid)
        with self._lock:
            rows = self._db.execute(f"""
                SELECT st.*, s.quote, s.expires_at FROM streets AS st
                JOIN sightings AS s ON st.id = s.street_id
                WHERE {" AND ".join(filters)}
                ORDER BY st.city, st.id, s.observed_at DESC, s.rowid DESC
            """, values).fetchall()

        streets: dict[str, Street] = {}
        for row in rows:
            street_id = row["id"]
            expires = datetime.fromtimestamp(row["expires_at"], tz=timezone.utc)
            if street_id not in streets:
                streets[street_id] = Street(
                    id=street_id, city=row["city"], street=row["street"], active=True,
                    quotes=[], expires_at=expires,
                    geometry=json.loads(row["geometry"]) if row["geometry"] else None,
                )
            item = streets[street_id]
            item.expires_at = max(item.expires_at, expires)
            item.quotes.append(Quote.model_validate_json(row["quote"]))
        return list(streets.values())

    def list_streets(self, city: str | None = None) -> list[Street]:
        if city is None:
            return self._streets()
        canonical = normalize_city(city.strip())
        return self._streets(city=canonical) if canonical else []

    def get_street(self, sid: str) -> Street | None:
        streets = self._streets(sid=sid)
        return streets[0] if streets else None

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sightings")
            self._db.execute("DELETE FROM streets")

    def close(self) -> None:
        with self._lock:
            self._db.close()


store = SightingsStore(settings.sightings_db_path if settings.store_backend == "sqlite" else ":memory:")
