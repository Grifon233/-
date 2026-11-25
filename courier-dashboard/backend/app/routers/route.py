"""GET /route — пешеходный маршрут через настроенный Valhalla."""
import json

import httpx
from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.services.cities import normalize_city
from app.services.geometry import sample_locations
from app.services.sightings import store

router = APIRouter()
_MAX_AVOID_LOCATIONS = 50
_NO_PATH = {154, 170, 171, 172, 441, 442}


@router.get("/route")
async def route(
    city: str = Query(min_length=1, max_length=100),
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lng: float = Query(ge=-180, le=180),
    avoid: str | None = Query(default=None, max_length=16),
) -> dict:
    if (canonical_city := normalize_city(city)) is None:
        raise HTTPException(status_code=422, detail="unknown_city")
    if avoid not in (None, "occupied"):
        raise HTTPException(status_code=422, detail="unsupported_avoid_mode")
    if not settings.valhalla_url:
        raise HTTPException(status_code=503, detail="valhalla_not_configured")

    payload: dict = {
        "locations": [
            {"lat": from_lat, "lon": from_lng},
            {"lat": to_lat, "lon": to_lng},
        ],
        "costing": "pedestrian",
    }

    if avoid == "occupied":
        occupied = await run_in_threadpool(store.list_streets, canonical_city)
        if len(occupied) > _MAX_AVOID_LOCATIONS:
            raise HTTPException(status_code=409, detail="too_many_occupied_streets")
        if occupied:
            per_street, remainder = divmod(_MAX_AVOID_LOCATIONS, len(occupied))
            avoid_locations = []
            for index, street in enumerate(occupied):
                limit = per_street + int(index < remainder)
                if not street.geometry or not (points := sample_locations(street.geometry, limit)):
                    raise HTTPException(status_code=409, detail="occupied_geometry_unavailable")
                avoid_locations.extend(points)
            payload["exclude_locations"] = avoid_locations

    result = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{settings.valhalla_url.rstrip('/')}/route", json=payload)
            try:
                result = response.json()
            except (ValueError, RecursionError):
                response.raise_for_status()
                raise
            response.raise_for_status()
        if (
            not isinstance(result, dict) or not isinstance(result.get("trip"), dict)
            or not isinstance(result["trip"].get("legs"), list) or not result["trip"]["legs"]
            or not all(
                isinstance(leg, dict) and isinstance(leg.get("shape"), str) and leg["shape"]
                for leg in result["trip"]["legs"]
            )
        ):
            raise HTTPException(status_code=502, detail="invalid_valhalla_response")
        result["avoidance_applied"] = "exclude_locations" in payload
        if result["avoidance_applied"]:
            result["avoidance_method"] = "sampled_locations"
        json.dumps(result, allow_nan=False)
        return result
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="valhalla_timeout") from exc
    except httpx.HTTPStatusError as exc:
        code = result.get("error_code") if isinstance(result, dict) else None
        if type(code) is int and code in _NO_PATH:
            raise HTTPException(status_code=404, detail="route_not_found") from exc
        raise HTTPException(status_code=502, detail="valhalla_error") from exc
    except (ValueError, RecursionError) as exc:
        raise HTTPException(status_code=502, detail="invalid_valhalla_response") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="valhalla_error") from exc
