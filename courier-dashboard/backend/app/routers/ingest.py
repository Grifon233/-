"""POST /ingest — приём сырого сообщения от сборщика."""
import asyncio
import hmac
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.schemas import IngestMessage, Quote
from app.services import extract as extract_svc
from app.services.cities import normalize_city
from app.services.geo import geocode_street
from app.services.sightings import store

router = APIRouter()


@dataclass
class Pending:
    lock: asyncio.Lock
    users: int = 0


_pending: dict[str, Pending] = {}


@asynccontextmanager
async def _event_lock(event_key: str):
    entry = _pending.get(event_key)
    if entry is None:
        entry = _pending[event_key] = Pending(asyncio.Lock())
    entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.users -= 1
        if entry.users == 0:
            _pending.pop(event_key, None)


def _duplicate(previous: tuple[str, str]) -> dict:
    return {"accepted": True, "duplicate": True, "city": previous[0], "street": previous[1]}


@router.post("/ingest")
async def ingest(msg: IngestMessage, x_api_key: str | None = Header(default=None)) -> dict:
    if settings.ingest_api_key:
        if not x_api_key or not hmac.compare_digest(
            x_api_key.encode("utf-8"), settings.ingest_api_key.encode("utf-8"),
        ):
            raise HTTPException(status_code=401, detail="invalid_api_key")
    elif not settings.ingest_allow_unauthenticated:
        raise HTTPException(status_code=503, detail="ingest_not_configured")

    now, observed = time.time(), msg.ts.timestamp()
    if observed > now + settings.sighting_max_future_skew:
        return {"accepted": False, "reason": "future_message"}
    expires_at = min(now, observed) + settings.sighting_ttl
    if expires_at <= now:
        return {"accepted": False, "reason": "stale_message"}

    event_key = f"{msg.source_chat.casefold()}:{msg.message_id}"
    async with _event_lock(event_key):
        if previous := await run_in_threadpool(store.find_event, event_key):
            return _duplicate(previous)
        private_source = msg.message_link.startswith("chat:")
        if private_source and not settings.llm_allow_private_text:
            data = await extract_svc.extract(msg.text, allow_external=False)
        else:
            data = await extract_svc.extract(msg.text)
        if data is None:
            return {"accepted": False, "reason": "not_a_sighting"}

        city = normalize_city(data.get("city")) or normalize_city(msg.city)
        if not city:
            return {"accepted": False, "reason": "unknown_city"}

        street = str(data["street"]).strip()
        geometry = await run_in_threadpool(store.get_geometry, city, street)
        if geometry is None:
            geometry = await geocode_street(city, street)

        # Приватный текст и идентификатор чата не возвращаются публичной карте.
        quote = Quote(
            text="Отметка из непубличного источника" if private_source else msg.text,
            link="" if private_source else msg.message_link,
            ts=msg.ts,
        )
        added = await run_in_threadpool(
            store.add, city, street, quote, event_key, expires_at, geometry,
        )
        if not added:
            if previous := await run_in_threadpool(store.find_event, event_key):
                return _duplicate(previous)
            return {"accepted": False, "reason": "stale_message"}
        return {
            "accepted": True,
            "duplicate": False,
            "city": city,
            "street": street,
            "geocoded": geometry is not None,
        }
