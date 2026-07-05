"""Геокодинг места через Nominatim с кэшем и лимитом один запрос в секунду."""
import asyncio
import logging
import time

import httpx

from app.config import settings
from app.services.cities import normalize_city

logger = logging.getLogger(__name__)
_cache: dict[tuple[str, str], dict | None] = {}
_request_lock = asyncio.Lock()
_last_request = 0.0


async def geocode_street(city: str, street: str) -> dict | None:
    """Вернуть GeoJSON-геометрию улицы/объекта или None."""
    global _last_request
    cache_key = (city.casefold().strip(), street.casefold().strip())
    if cache_key in _cache:
        return _cache[cache_key]

    async with _request_lock:
        if cache_key in _cache:
            return _cache[cache_key]
        delay = 1.0 - (time.monotonic() - _last_request)
        if delay > 0:
            await asyncio.sleep(delay)

        params = {
            "street": street,
            "city": city,
            "countrycodes": "ru",
            "format": "jsonv2",
            "polygon_geojson": 1,
            "addressdetails": 1,
            "limit": 5,
        }
        headers = {"User-Agent": settings.geocoding_user_agent}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(
                    f"{settings.nominatim_url.rstrip('/')}/search",
                    params=params,
                    headers=headers,
                )
                _last_request = time.monotonic()
                response.raise_for_status()
                results = response.json()
            geometry = None
            for result in results:
                address = result.get("address", {})
                locality_values = [
                    address.get("city"),
                    address.get("town"),
                    address.get("municipality"),
                    address.get("state"),
                ]
                if city not in {
                    normalize_city(value)
                    for value in locality_values
                    if value
                }:
                    continue
                geometry = result.get("geojson")
                break
            if not isinstance(geometry, dict) or "type" not in geometry:
                geometry = None
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            logger.exception("Geocoding failed for %s, %s", street, city)
            geometry = None

        _cache[cache_key] = geometry
        return geometry


def clear_geo_cache() -> None:
    _cache.clear()
