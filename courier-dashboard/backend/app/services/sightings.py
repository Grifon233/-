"""Хранилище отметок с TTL 2 часа (см. docs/02, шаг 5).

Локально — в памяти (STORE_BACKEND=memory). На сервере заменим на Redis/Postgres,
интерфейс store.add()/store.list_streets()/store.get_street() остаётся тем же.
Несколько отметок на одной улице не дублируют улицу, а копят список цитат.
Улица 'active', пока жива хотя бы одна отметка.
"""
import time
from datetime import datetime, timezone

from app.config import settings
from app.schemas import Quote, Street


def _street_id(city: str, street: str) -> str:
    return f"{city.lower().strip()}::{street.lower().strip()}"


class MemoryStore:
    def __init__(self) -> None:
        # street_id -> {"city","street", "quotes": [(quote, expires_epoch, event_key), ...]}
        self._data: dict[str, dict] = {}
        self._events: dict[str, tuple[str, float]] = {}

    def _purge(self, sid: str) -> None:
        """Убрать протухшие цитаты; удалить улицу, если живых не осталось."""
        now = time.time()
        item = self._data.get(sid)
        if not item:
            return
        alive = []
        for quote, expires, event_key in item["quotes"]:
            if expires > now:
                alive.append((quote, expires, event_key))
            elif event_key:
                self._events.pop(event_key, None)
        item["quotes"] = alive
        if not item["quotes"]:
            self._data.pop(sid, None)

    def purge_expired(self) -> None:
        for sid in list(self._data):
            self._purge(sid)

    def add(
        self,
        city: str,
        street: str,
        quote: Quote,
        event_key: str | None = None,
        geometry: dict | None = None,
    ) -> bool:
        """Добавить отметку. False означает уже обработанное событие."""
        self.purge_expired()
        now = time.time()
        if event_key:
            previous = self._events.get(event_key)
            if previous and previous[1] > now:
                return False
            if previous:
                self._events.pop(event_key, None)

        sid = _street_id(city, street)
        item = self._data.setdefault(
            sid,
            {"city": city, "street": street, "quotes": [], "geometry": geometry},
        )
        if item.get("geometry") is None and geometry is not None:
            item["geometry"] = geometry
        expires = now + settings.sighting_ttl
        item["quotes"].append((quote, expires, event_key))
        if event_key:
            self._events[event_key] = (sid, expires)
        return True

    def has_event(self, event_key: str) -> bool:
        self.purge_expired()
        event = self._events.get(event_key)
        return bool(event and event[1] > time.time())

    def get_street(self, sid: str) -> Street | None:
        self._purge(sid)
        item = self._data.get(sid)
        if not item:
            return None
        quotes = [q for q, _, _ in item["quotes"]]
        latest_exp = max(exp for _, exp, _ in item["quotes"])
        return Street(
            id=sid, city=item["city"], street=item["street"], active=True,
            quotes=quotes,
            expires_at=datetime.fromtimestamp(latest_exp, tz=timezone.utc),
            geometry=item.get("geometry"),
        )

    def list_streets(self, city: str | None = None) -> list[Street]:
        self.purge_expired()
        out: list[Street] = []
        for sid in list(self._data.keys()):
            s = self.get_street(sid)
            if s and (city is None or s.city.lower() == city.lower()):
                out.append(s)
        return out

    def clear(self) -> None:
        self._data.clear()
        self._events.clear()


# Единый экземпляр хранилища на процесс.
store = MemoryStore()
