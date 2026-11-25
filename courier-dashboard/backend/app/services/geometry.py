"""Проверка GeoJSON от геокодера и выборка точек для маршрутизатора."""
import math


def normalize_geometry(data: object) -> dict | None:
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        return None
    kind = data["type"]
    levels = {
        "Point": (),
        "MultiPoint": (1,),
        "LineString": (2,),
        "MultiLineString": (1, 2),
        "Polygon": (1, 4),
        "MultiPolygon": (1, 1, 4),
    }
    if kind not in levels:
        return None

    count = 0

    def clean(value: object, minima: tuple) -> list:
        nonlocal count
        if not isinstance(value, list):
            raise ValueError
        if minima:
            if len(value) < minima[0] or len(value) > 20_000:
                raise ValueError
            result = [clean(child, minima[1:]) for child in value]
            if minima == (4,) and result[0] != result[-1]:
                raise ValueError
            return result
        count += 1
        if count > 20_000 or not 2 <= len(value) <= 3:
            raise ValueError
        lon, lat = value[:2]
        if (
            type(lon) not in (float, int) or type(lat) not in (float, int)
            or not -180 <= lon <= 180 or not -90 <= lat <= 90
        ):
            raise ValueError
        return [lon, lat]

    try:
        return {"type": kind, "coordinates": clean(data.get("coordinates"), levels[kind])}
    except ValueError:
        return None


def sample_locations(geometry: dict, limit: int) -> list[dict[str, float]]:
    """Примерно равномерная выборка вдоль сегментов вместо отбора начальных вершин."""
    if limit <= 0 or (data := normalize_geometry(geometry)) is None:
        return []
    kind, coordinates = data["type"], data["coordinates"]
    if kind in {"Point", "MultiPoint"}:
        points = [coordinates] if kind == "Point" else coordinates
        if len(points) > limit:
            points = [points[min(len(points) - 1, int((i + 0.5) * len(points) / limit))] for i in range(limit)]
    else:
        if kind == "LineString":
            lines = [coordinates]
        elif kind == "MultiPolygon":
            lines = [ring for polygon in coordinates for ring in polygon]
        else:
            lines = coordinates
        segments = []
        total = 0.0
        for line in lines:
            for a, b in zip(line, line[1:]):
                scale = math.cos(math.radians((a[1] + b[1]) / 2))
                length = 111_320 * math.hypot((b[0] - a[0]) * scale, b[1] - a[1])
                if length > 0:
                    total += length
                    segments.append((total, length, a, b))
        if not segments:
            points = [lines[0][0]]
        else:
            sample_count = min(limit, max(1, math.ceil(total / 40)))
            goals = [(i + 0.5) * total / sample_count for i in range(sample_count)]
            points = []
            index = 0
            for goal in goals:
                while index < len(segments) - 1 and segments[index][0] < goal:
                    index += 1
                end, length, a, b = segments[index]
                part = (goal - (end - length)) / length
                points.append([x + ((y - x) * part) for x, y in zip(a, b)])
    return [{"lat": point[1], "lon": point[0]} for point in points]
