"""Random profile presets for the account profile editor.

The frontend cannot read arbitrary Windows folders, so this small
service exposes a safe, read-only picker for the local avatar library.
It returns a random first name plus one image from the gender-specific
folder as base64, and the profile editor turns that payload into an
ordinary File before saving/uploading it.
"""
from __future__ import annotations

import base64
import re
import mimetypes
import os
import random
from pathlib import Path
from typing import Literal


Gender = Literal["male", "female"]
Locale = Literal["ru", "en"]


# Avatar library now lives INSIDE the project (``src/backend/var/profile_photos``)
# so the app is self-contained and doesn't depend on a folder on the
# operator's desktop. An env override is still honoured.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PHOTO_LIBRARY = Path(
    os.getenv(
        "PROFILE_PHOTO_LIBRARY_PATH",
        str(_BACKEND_ROOT / "var" / "profile_photos"),
    )
)

PHOTO_FOLDERS = {
    "male": "Мужчины",
    "female": "Девушки",
}

NAMES: dict[Gender, dict[Locale, list[str]]] = {
    "male": {
        "ru": [
            "Алексей", "Дмитрий", "Иван", "Михаил", "Андрей", "Сергей",
            "Никита", "Павел", "Егор", "Артём", "Кирилл", "Максим",
            "Роман", "Илья", "Владимир", "Даниил",
        ],
        "en": [
            "Alex", "Daniel", "Michael", "Andrew", "James", "David",
            "Nick", "Paul", "Ethan", "Ryan", "Chris", "Mark",
            "John", "Leo", "Victor", "Thomas",
        ],
    },
    "female": {
        "ru": [
            "Анна", "Мария", "Екатерина", "Алина", "Виктория", "София",
            "Дарья", "Полина", "Ксения", "Елена", "Анастасия", "Ирина",
            "Ольга", "Юлия", "Валерия", "Наталья",
        ],
        "en": [
            "Anna", "Maria", "Kate", "Alina", "Victoria", "Sophie",
            "Diana", "Paula", "Kira", "Helen", "Stacy", "Irene",
            "Olivia", "Julia", "Valerie", "Natalie",
        ],
    },
}

LAST_NAMES: dict[Gender, dict[Locale, list[str]]] = {
    "male": {
        "ru": [
            "Смирнов", "Соколов", "Морозов", "Волков", "Фёдоров", "Орлов",
            "Козлов", "Новиков", "Егоров", "Павлов", "Романов", "Макаров",
            "Кириллов", "Ильин", "Власов", "Тихонов",
        ],
        "en": [
            "Smith", "Miller", "Parker", "Brooks", "Foster", "Reed",
            "Turner", "Morgan", "Cooper", "Bennett", "Walker", "Hayes",
            "Carter", "Harris", "Lewis", "Evans",
        ],
    },
    "female": {
        "ru": [
            "Смирнова", "Соколова", "Морозова", "Волкова", "Фёдорова",
            "Орлова", "Козлова", "Новикова", "Егорова", "Павлова",
            "Романова", "Макарова", "Кириллова", "Ильина", "Власова",
            "Тихонова",
        ],
        "en": [
            "Smith", "Miller", "Parker", "Brooks", "Foster", "Reed",
            "Turner", "Morgan", "Cooper", "Bennett", "Walker", "Hayes",
            "Carter", "Harris", "Lewis", "Evans",
        ],
    },
}

USERNAME_WORDS: dict[Locale, list[str]] = {
    "ru": [
        "north", "river", "field", "stone", "light", "urban", "forest",
        "quiet", "coffee", "signal", "cloud", "amber", "vector", "studio",
    ],
    "en": [
        "north", "river", "field", "stone", "light", "urban", "forest",
        "quiet", "coffee", "signal", "cloud", "amber", "vector", "studio",
    ],
}

# Neutral prefixes only — never anything that hints at a country,
# region or language (no "ru"/"en"/"msk"/"spb"), because that ties the
# generated handle to a locale and looks templated. Kept generic so a
# username reads like a normal person's handle.
USERNAME_PREFIXES = [
    "tg",
    "tg24",
    "tg25",
    "life",
    "life24",
    "daily",
    "city",
    "city25",
    "note",
    "real",
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def build_random_profile_preset(gender: Gender, locale: Locale = "ru") -> dict:
    """Return a random name and avatar payload for ``gender`` / ``locale``."""
    names = NAMES.get(gender, {}).get(locale)
    last_names = LAST_NAMES.get(gender, {}).get(locale)
    if not names or not last_names:
        raise ValueError("Unsupported gender or locale")

    folder = PROFILE_PHOTO_LIBRARY / PHOTO_FOLDERS[gender]
    if not folder.exists():
        raise FileNotFoundError(f"Avatar folder not found: {folder}")

    photos = [
        item for item in folder.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not photos:
        raise FileNotFoundError(f"No avatar images found in: {folder}")

    photo = random.choice(photos)
    first_name = random.choice(names)
    last_name = random.choice(last_names)
    mime_type = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
    return {
        "first_name": first_name,
        "last_name": last_name,
        "username": _build_username(first_name, last_name, locale),
        "gender": gender,
        "locale": locale,
        "avatar_filename": photo.name,
        "avatar_mime_type": mime_type,
        "avatar_base64": base64.b64encode(photo.read_bytes()).decode("ascii"),
    }


def _build_username(first_name: str, last_name: str, locale: Locale) -> str:
    """Build a human-looking Telegram username candidate.

    Telegram requires latin letters/digits/underscore and 5-32 chars,
    so Russian names are transliterated before composing the handle.
    The username can still be occupied; the profile save endpoint will
    surface Telegram's real answer in that case.
    """
    first = _slug(first_name)
    last = _slug(last_name)
    word = random.choice(USERNAME_WORDS[locale])
    variants = [
        f"{first}_{last}",
        f"{first}.{last}",
        f"{first}{last}",
        f"{first}_{word}",
        f"{word}_{first}",
    ]
    base = random.choice(variants).replace(".", "_")
    prefix = random.choice(USERNAME_PREFIXES)
    suffix = random.choice(
        [
            str(random.randint(24, 29)),
            str(random.randint(70, 99)),
            str(random.randint(100, 999)),
        ]
    )
    username = f"{prefix}_{base}{suffix}"
    username = re.sub(r"[^A-Za-z0-9_]", "", username)
    if not username or not username[0].isalpha():
        username = f"user_{username}"
    return username[:32]


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = "".join(_TRANSLIT.get(char, char) for char in value)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or "user"
