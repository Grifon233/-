import os
from dotenv import load_dotenv

load_dotenv()


def _split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_DISK_TOKEN = os.getenv("YANDEX_DISK_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1003926052423"))
FORUM_CHAT_ID = int(os.getenv("FORUM_CHAT_ID", "-1003513353571"))
FORUM_MESSAGE_THREAD_ID = os.getenv("FORUM_MESSAGE_THREAD_ID")
FORUM_MESSAGE_THREAD_ID = int(FORUM_MESSAGE_THREAD_ID) if FORUM_MESSAGE_THREAD_ID else None
YANDEX_DISK_BASE_PATH = os.getenv("YANDEX_DISK_BASE_PATH")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

# Тренер - Яна Вегера
TRAINER_ID = int(os.getenv("TRAINER_ID", "526772184"))
# Разработчик - Костя Колод
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", "623597334"))

# Список спортсменов и тренеров
ATHLETES = {
    526772184: {
        "name": "Вегера",
        "full_name": "Яна",
        "role": "trainer",
        "aliases": ["яна", "вегера", "яночка", "януся", "вег"]
    },
    485828610: {
        "name": "Кочуров",
        "full_name": "Ваня",
        "role": "athlete",
        "aliases": ["ваня", "иван", "кочуров", "ванюша", "иванушка", "ванька", "кочур", "кочу", "вань"]
    },
    6927701687: {
        "name": "Маккинли",
        "full_name": "Катя",
        "role": "athlete",
        "aliases": ["катя", "екатерина", "маккинли", "катерина", "катюша", "катька", "кэт", "кат", "макинли"]
    },
    5117209800: {
        "name": "Иванов",
        "full_name": "Кирилл",
        "role": "athlete",
        "aliases": ["иванов", "кирилл", "кирил", "кирюша", "кир", "киря"]
    },
    947530704: {
        "name": "Саврук",
        "full_name": "Настя",
        "role": "athlete",
        "aliases": ["настя", "анастасия", "саврук", "настюша", "настенька", "нась", "настюха", "савр"]
    },
    963736752: {
        "name": "Степанов",
        "full_name": "Серёга",
        "role": "athlete",
        "aliases": ["серёга", "сергей", "степанов", "сержа", "серёжа", "серега", "степа", "степ", "серый", "серж"]
    },
    940641912: {
        "name": "Андреев",
        "full_name": "Саня",
        "role": "athlete",
        "aliases": ["саня", "александр", "андреев", "саша", "сашка", "санек", "сан", "шурик"]
    },
    6080652187: {
        "name": "Фролова",
        "full_name": "Лиза",
        "role": "athlete",
        "aliases": ["лиза", "елизавета", "фролова", "лизок", "лизочек", "элизабет", "лиз", "фрол"]
    },
    623597334: {
        "name": "Колод",
        "full_name": "Костя",
        "role": "athlete",
        "aliases": ["костя", "костян", "костик", "константин", "колод", "кост", "кость", "кос"]
    },
    7316068581: {
        "name": "Зельдин",
        "full_name": "Лев",
        "role": "athlete",
        "aliases": ["лев", "зельдин", "левка", "левон", "лева", "лёва", "зелд", "зель"]
    },
    1730524927: {
        "name": "Власов",
        "full_name": "Никита",
        "role": "athlete",
        "aliases": ["никита", "власов", "никитка", "никитос", "ник", "влас", "никит"]
    },
}

# API-ключи для LLM (роутинг). Хранятся только в окружении.
LLM_KEYS = {
    "cloudflare": _split_env_list(os.getenv("CLOUDFLARE_API_KEYS")),
    "openrouter": _split_env_list(os.getenv("OPENROUTER_API_KEYS")),
    "mistral": _split_env_list(os.getenv("MISTRAL_API_KEYS")),
    "cohere": _split_env_list(os.getenv("COHERE_API_KEYS")),
    "aihubmix": _split_env_list(os.getenv("AIHUBMIX_API_KEYS")),
}

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

VIDEO_FORMATS = [".mp4", ".mov", ".avi", ".mkv"]
MIN_VIDEOS_COUNT = 6
TRAINER_CONFIRMATION_TIMEOUT = 420  # 7 минут

WEEKDAYS = {
    "пн": 0, "понедельник": 0,
    "вт": 1, "вторник": 1,
    "ср": 2, "среда": 2,
    "чт": 3, "четверг": 3,
    "пт": 4, "пятница": 4,
    "сб": 5, "суббота": 5,
    "вс": 6, "воскресенье": 6,
}

# ID спортсменов для рассылки (без тренеров)
ATHLETE_IDS = [tid for tid, data in ATHLETES.items() if data.get("role") == "athlete"]
