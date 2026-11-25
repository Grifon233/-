"""Геокодинг через настроенный Nominatim с ограничением нагрузки."""
import asyncio
import logging
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.cities import normalize_city
from app.services.geometry import normalize_geometry
from app.services.street_names import street_key

logger = logging.getLogger(__name__)
_cache: OrderedDict[tuple[str, str], tuple[float, dict | None]] = OrderedDict()
_MAX_CACHE_ENTRIES = 2048
_request_lock = asyncio.Lock()
_last_request: float | None = None


def _cached(key: tuple[str, str]) -> tuple[bool, dict | None]:
    entry = _cache.get(key)
    if entry is None:
        return False, None
    expires, geometry = entry
    if expires <= time.monotonic():
        _cache.pop(key, None)
        return False, None
    _cache.move_to_end(key)
    return True, geometry


async def _lookup(base_url: str, city: str, street: str, cache_key: tuple[str, str]) -> dict | None:
    global _last_request
    async with _request_lock:
        found, geometry = _cached(cache_key)
        if found:
            return geometry

        is_public = urlsplit(base_url).hostname == "nominatim.openstreetmap.org"
        interval = 15.0 if is_public else 1.0
        if _last_request is not None:
            delay = interval - (time.monotonic() - _last_request)
            if delay > 0:
                await asyncio.sleep(delay)
        _last_request = time.monotonic()

        params = {
            "street": street,
            "city": city,
            "countrycodes": "ru",
            "format": "jsonv2",
            "polygon_geojson": 1,
            "polygon_threshold": 0.00005,
            "addressdetails": 1,
            "limit": 5,
        }
        headers = {"User-Agent": settings.geocoding_user_agent}
        ttl = 300
        try:
            async with httpx.AsyncClient(timeout=settings.geocoding_timeout) as client:
                response = await client.get(f"{base_url.rstrip('/')}/search", params=params, headers=headers)
                response.raise_for_status()
                results = response.json()
            if not isinstance(results, list):
                raise ValueError("geocoder results are not a list")
            for result in results:
                if not isinstance(result, dict):
                    continue
                address = result.get("address")
                if not isinstance(address, dict):
                    continue
                locality_fields = ("city", "town", "village", "municipality")
                # Только города федерального значения также имеют статус региона.
                if city in {"Москва", "Санкт-Петербург"}:
                    locality_fields += ("state",)
                if city not in {normalize_city(address.get(field)) for field in locality_fields}:
                    continue
                if (geometry := normalize_geometry(result.get("geojson"))) is not None:
                    ttl = 86400
                    break
        except (httpx.HTTPError, ValueError, RecursionError) as exc:
            logger.warning("Geocoding failed (%s)", type(exc).__name__)
            ttl = 15

        _cache[cache_key] = (time.monotonic() + ttl, geometry)
        if len(_cache) > _MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)
        return geometry


async def geocode_street(city: str, street: str) -> dict | None:
    """Геометрия или None. Весь поиск, включая очередь, имеет общий бюджет времени."""
    if not settings.nominatim_url:
        return None
    key = (city.casefold(), street_key(street))
    found, geometry = _cached(key)
    if found:
        return geometry
    try:
        return await asyncio.wait_for(
            _lookup(settings.nominatim_url, city, street, key), timeout=settings.geocoding_timeout,
        )
    except TimeoutError:
        logger.warning("Geocoding exceeded total time budget")
        return None


def clear_geo_cache() -> None:
    global _last_request
    _cache.clear()
    _last_request = None
