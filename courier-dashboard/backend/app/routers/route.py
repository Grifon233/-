"""GET /route — маршрут, при avoid=occupied строится в обход занятых улиц (см. docs/03).

Использует Valhalla (exclude_polygons). Если VALHALLA_URL пуст — отдаёт 503,
чтобы было явно видно, что маршрутизатор ещё не подключён.
"""
import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.services.sightings import store

router = APIRouter()


def _geometry_points(geometry: dict, limit: int = 80) -> list[dict[str, float]]:
    coordinates = geometry.get("coordinates")
    points: list[list[float]] = []

    def collect(value) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and all(isinstance(v, (int, float)) for v in value[:2])
        ):
            points.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(coordinates)
    if not points:
        return []
    step = max(1, len(points) // limit)
    return [
        {"lat": point[1], "lon": point[0]}
        for point in points[::step][:limit]
    ]


@router.get("/route")
async def route(
    city: str,
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lng: float = Query(ge=-180, le=180),
    avoid: str | None = None,   # avoid=occupied -> обходить занятые улицы
) -> dict:
    if not settings.valhalla_url:
        raise HTTPException(status_code=503, detail="valhalla_not_configured")

    payload: dict = {
        "locations": [
            {"lat": from_lat, "lon": from_lng},
            {"lat": to_lat, "lon": to_lng},
        ],
        "costing": "pedestrian",
    }

    if avoid not in (None, "occupied"):
        raise HTTPException(status_code=422, detail="unsupported_avoid_mode")

    if avoid == "occupied":
        occupied = store.list_streets(city=city)
        avoid_locations: list[dict[str, float]] = []
        for street in occupied:
            if street.geometry:
                avoid_locations.extend(_geometry_points(street.geometry))
        if occupied and not avoid_locations:
            raise HTTPException(status_code=409, detail="occupied_geometry_unavailable")
        if avoid_locations:
            payload["exclude_locations"] = avoid_locations[:100]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{settings.valhalla_url.rstrip('/')}/route",
                json=payload,
            )
            r.raise_for_status()
            result = r.json()
            result["avoidance_applied"] = bool(payload.get("exclude_locations"))
            return result
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="valhalla_timeout") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="valhalla_error") from exc
