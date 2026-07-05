DEFAULT_TIMEZONE = "Europe/Moscow"

RUSSIAN_TIMEZONES = {
    "kaliningrad": ("Калининград", "Europe/Kaliningrad", "UTC+2"),
    "moscow": ("Москва", "Europe/Moscow", "UTC+3"),
    "samara": ("Самара", "Europe/Samara", "UTC+4"),
    "yekaterinburg": ("Екатеринбург", "Asia/Yekaterinburg", "UTC+5"),
    "omsk": ("Омск", "Asia/Omsk", "UTC+6"),
    "krasnoyarsk": ("Красноярск", "Asia/Krasnoyarsk", "UTC+7"),
    "irkutsk": ("Иркутск", "Asia/Irkutsk", "UTC+8"),
    "yakutsk": ("Якутск", "Asia/Yakutsk", "UTC+9"),
    "vladivostok": ("Владивосток", "Asia/Vladivostok", "UTC+10"),
    "magadan": ("Магадан", "Asia/Magadan", "UTC+11"),
    "kamchatka": ("Камчатка", "Asia/Kamchatka", "UTC+12"),
}

VALID_RUSSIAN_TIMEZONES = {item[1] for item in RUSSIAN_TIMEZONES.values()}
