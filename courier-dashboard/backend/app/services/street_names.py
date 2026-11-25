"""Нормализация написания для ключа улицы, не подмена отображаемого названия."""
import re
import unicodedata

_TYPES = {
    "улица": "улица", "ул": "улица",
    "проспект": "проспект", "пр-т": "проспект",
    "переулок": "переулок", "пер": "переулок",
    "шоссе": "шоссе", "бульвар": "бульвар", "бул": "бульвар",
    "набережная": "набережная", "наб": "набережная",
    "площадь": "площадь", "пл": "площадь", "проезд": "проезд",
}


def street_key(street: str) -> str:
    value = unicodedata.normalize("NFKC", street).casefold().replace("ё", "е")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    parts = value.split()
    if len(parts) < 2:
        return " ".join(parts)
    if (kind := _TYPES.get(parts[0].rstrip("."))) is not None:
        return " ".join([kind, *parts[1:]])
    if (kind := _TYPES.get(parts[-1].rstrip("."))) is not None:
        return " ".join([kind, *parts[:-1]])
    return " ".join(parts)
