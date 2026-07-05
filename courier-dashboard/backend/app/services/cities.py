"""Канонизация названий поддерживаемых городов."""
import re
import unicodedata

CITY_ALIASES = {
    "Москва": {"москва", "moscow", "г москва", "город москва", "мск"},
    "Санкт-Петербург": {
        "санкт петербург", "санкт-петербург", "saint petersburg",
        "st petersburg", "спб", "питер",
    },
    "Новосибирск": {"новосибирск", "novosibirsk", "нск"},
    "Екатеринбург": {"екатеринбург", "yekaterinburg", "ekaterinburg", "екб"},
    "Казань": {"казань", "kazan"},
}


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", value).strip()


_LOOKUP = {
    _key(alias): canonical
    for canonical, aliases in CITY_ALIASES.items()
    for alias in aliases | {canonical}
}


def normalize_city(value: str | None) -> str | None:
    if not value:
        return None
    return _LOOKUP.get(_key(value))
