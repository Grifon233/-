"""POST /ingest — приём сырого сообщения от сборщика (см. docs/02)."""
import hmac

from fastapi import APIRouter, Header, HTTPException

from app.schemas import IngestMessage, Quote
from app.config import settings
from app.services import extract as extract_svc
from app.services.cities import normalize_city
from app.services.geo import geocode_street
from app.services.sightings import store

router = APIRouter()


@router.post("/ingest")
async def ingest(msg: IngestMessage, x_api_key: str | None = Header(default=None)) -> dict:
    if settings.ingest_api_key and not (
        x_api_key and hmac.compare_digest(x_api_key, settings.ingest_api_key)
    ):
        raise HTTPException(status_code=401, detail="invalid_api_key")

    data = await extract_svc.extract(msg.text)
    if data is None:
        return {"accepted": False, "reason": "not_a_sighting"}

    city = normalize_city(data.get("city")) or normalize_city(msg.city)
    if not city:
        return {"accepted": False, "reason": "unknown_city"}

    street = str(data["street"]).strip()
    if not street:
        return {"accepted": False, "reason": "unknown_street"}

    quote = Quote(text=msg.text, link=msg.message_link, ts=msg.ts)
    event_key = f"{msg.source_chat.strip().lower()}:{msg.message_id}"
    if store.has_event(event_key):
        return {"accepted": True, "duplicate": True, "city": city, "street": street}
    geometry = await geocode_street(city, street)
    added = store.add(
        city=city,
        street=street,
        quote=quote,
        event_key=event_key,
        geometry=geometry,
    )
    if not added:
        return {"accepted": True, "duplicate": True, "city": city, "street": street}
    return {
        "accepted": True,
        "duplicate": False,
        "city": city,
        "street": street,
        "geocoded": geometry is not None,
    }
