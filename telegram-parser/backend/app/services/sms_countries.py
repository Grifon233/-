"""ISO country code ⇄ smsfast (SMS-Activate-compatible) country IDs.

smsfast.cc uses the de-facto-standard SMS-Activate numeric country
numbering (verified live for RU=0, UA=1, KZ=2, US=12, GB=16). This
module maps the 2-letter ISO codes that proxies are tagged with
(``proxy.country``) to those numeric IDs so "order a number in the
same country as the proxy" works automatically.

Only well-established IDs are included. When a proxy's country has no
mapping here the UI lets the operator pick a country manually, so an
unmapped ISO code is a soft failure, not a crash.
"""
from __future__ import annotations

from typing import Optional

# ISO-3166 alpha-2 → smsfast numeric country id.
ISO_TO_SMSFAST: dict[str, int] = {
    "RU": 0,    # Russia (note: no Telegram virtual numbers available)
    "UA": 1,    # Ukraine
    "KZ": 2,    # Kazakhstan
    "CN": 3,    # China
    "PH": 4,    # Philippines
    "MM": 5,    # Myanmar
    "ID": 6,    # Indonesia
    "MY": 7,    # Malaysia
    "KE": 8,    # Kenya
    "TZ": 9,    # Tanzania
    "VN": 10,   # Vietnam
    "KG": 11,   # Kyrgyzstan
    "US": 12,   # United States (virtual)
    "IL": 13,   # Israel
    "HK": 14,   # Hong Kong
    "PL": 15,   # Poland
    "GB": 16,   # United Kingdom
    "NG": 19,   # Nigeria
    "MO": 20,   # Macau
    "EG": 21,   # Egypt
    "IN": 22,   # India
    "IE": 23,   # Ireland
    "KH": 24,   # Cambodia
    "LA": 25,   # Laos
    "RS": 29,   # Serbia
    "ZA": 31,   # South Africa
    "RO": 32,   # Romania
    "CO": 33,   # Colombia
    "EE": 34,   # Estonia
    "AZ": 35,   # Azerbaijan
    "CA": 36,   # Canada
    "MA": 38,   # Morocco
    "GH": 39,   # Ghana
    "AR": 40,   # Argentina
    "UZ": 41,   # Uzbekistan
    "DE": 43,   # Germany
    "LT": 44,   # Lithuania
    "HR": 45,   # Croatia
    "SE": 46,   # Sweden
    "NL": 48,   # Netherlands
    "LV": 49,   # Latvia
    "AT": 50,   # Austria
    "BY": 51,   # Belarus
    "TH": 52,   # Thailand
    "SA": 53,   # Saudi Arabia
    "MX": 54,   # Mexico
    "TW": 55,   # Taiwan
    "ES": 56,   # Spain
    "TR": 62,   # Turkey
    "BR": 73,   # Brazil
    "FR": 78,   # France
    "IT": 86,   # Italy
    "PT": 117,  # Portugal
    "GE": 128,  # Georgia
    "AM": 148,  # Armenia
}

# Russian display names for the numeric IDs (used in the UI dropdown).
SMSFAST_COUNTRY_NAMES: dict[int, str] = {
    0: "Россия", 1: "Украина", 2: "Казахстан", 3: "Китай", 4: "Филиппины",
    5: "Мьянма", 6: "Индонезия", 7: "Малайзия", 8: "Кения", 9: "Танзания",
    10: "Вьетнам", 11: "Кыргызстан", 12: "США", 13: "Израиль", 14: "Гонконг",
    15: "Польша", 16: "Великобритания", 19: "Нигерия", 20: "Макао",
    21: "Египет", 22: "Индия", 23: "Ирландия", 24: "Камбоджа", 25: "Лаос",
    29: "Сербия", 31: "ЮАР", 32: "Румыния", 33: "Колумбия", 34: "Эстония",
    35: "Азербайджан", 36: "Канада", 38: "Марокко", 39: "Гана",
    40: "Аргентина", 41: "Узбекистан", 43: "Германия", 44: "Литва",
    45: "Хорватия", 46: "Швеция", 48: "Нидерланды", 49: "Латвия",
    50: "Австрия", 51: "Беларусь", 52: "Таиланд", 53: "Саудовская Аравия",
    54: "Мексика", 55: "Тайвань", 56: "Испания", 62: "Турция", 73: "Бразилия",
    78: "Франция", 86: "Италия", 117: "Португалия", 128: "Грузия",
    148: "Армения",
}


def country_id_for_iso(iso: Optional[str]) -> Optional[int]:
    """Map a 2-letter ISO code (case-insensitive) to a smsfast id, or None."""
    if not iso:
        return None
    return ISO_TO_SMSFAST.get(iso.strip().upper())


def country_name(country_id: int) -> str:
    """Human-readable name for a smsfast country id (falls back to the id)."""
    return SMSFAST_COUNTRY_NAMES.get(country_id, f"Страна #{country_id}")
