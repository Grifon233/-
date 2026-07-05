from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config.json"
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "leads.db"


DEFAULT_CONFIG: dict[str, Any] = {
    "scan_interval_hours": 2,
    "max_age_days": 14,
    "min_score": 4,
    "request_timeout_seconds": 25,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "web": {
        "host": "127.0.0.1",
        "port": 8080,
    },
    "sources": {
        "kwork": {
            "enabled": True,
            "pages": 2,
            "categories": [41, 38, 56, 113, 55],
            "category_names": {
                "38": "Доработка и настройка сайта",
                "41": "Скрипты и боты",
                "55": "Обучение и консалтинг",
                "56": "Статистика и аналитика",
                "113": "Базы данных и клиентов",
            },
        },
        "fl_ru": {
            "enabled": True,
            "categories": [5],
            "detail_pages": 4,
        },
        "freelance_ru": {
            "enabled": True,
            "pages": 3,
            "categories": [4, 724, 133],
        },
    },
    "positive_keywords": [
        "чат-бот",
        "чат бот",
        "telegram бот",
        "телеграм бот",
        "тг-бот",
        "tg bot",
        "bot",
        "бот",
        "бота",
        "ботов",
        "боты",
        "whatsapp",
        "wa bot",
        "mini app",
        "автоматизация",
        "автоматизации",
        "автоматизацию",
        "автоматизировать",
        "бизнес-процесс",
        "бизнес процесс",
        "интеграция",
        "интеграции",
        "интеграцию",
        "api",
        "webhook",
        "парсер",
        "парсинг",
        "scraping",
        "скрипт",
        "скрипта",
        "скрипты",
        "crm",
        "amoCRM",
        "amocrm",
        "битрикс24",
        "bitrix24",
        "1с",
        "erp",
        "ai",
        "ии",
        "gpt",
        "chatgpt",
        "openai",
        "yandexgpt",
        "нейросеть",
        "нейросети",
        "llm",
        "n8n",
        "make.com",
        "zapier",
        "airtable",
        "google sheets",
        "таблицы",
        "лиды",
        "воронка",
        "заявки",
        "рассылка",
    ],
    "weak_keywords": [
        "ai",
        "ии",
        "api",
        "1с",
        "скрипт",
        "скрипта",
        "скрипты",
        "таблицы",
        "лиды",
        "заявки",
        "рассылка",
    ],
    "negative_keywords": [
        "логотип",
        "брендинг",
        "визитка",
        "баннер",
        "иллюстрация",
        "фотошоп",
        "figma",
        "верстка",
        "копирайт",
        "рерайт",
        "перевод текста",
        "курсовая",
        "диплом",
        "отзыв",
        "накрут",
        "абуз",
        "казино",
        "ставки",
        "беттинг",
        "betting",
        "игра",
        "игры",
        "game",
        "gaming",
        "tanks",
        "battle city",
        "интервью",
        "подмена голоса",
    ],
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_config() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_config() -> dict[str, Any]:
    ensure_config()
    file_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = _deep_merge(DEFAULT_CONFIG, file_config)

    port = os.getenv("LEAD_MONITOR_PORT")
    if port:
        config["web"]["port"] = int(port)

    return config
