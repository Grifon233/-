import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_BOT_INSTRUCTION_VIDEO = PROJECT_ROOT / "assets" / "telegram_bot_instruction.mp4"
VK_BOT_INSTRUCTION_VIDEO = PROJECT_ROOT / "assets" / "vk_bot_instruction.mp4"
TELEGRAM_BOT_INSTRUCTION_PUBLIC_PATH = "/tutorials/telegram_bot_instruction.mp4"
VK_BOT_INSTRUCTION_PUBLIC_PATH = "/tutorials/vk_bot_instruction.mp4"
_CACHE_FILENAME = "tutorial_media_cache.json"
_TELEGRAM_CACHE_KEYS = {
    "telegram": "telegram_bot_instruction_video_file_id_20260621",
    "vk": "vk_bot_instruction_video_file_id_20260621",
}


def telegram_bot_instruction_video_path() -> Path:
    return TELEGRAM_BOT_INSTRUCTION_VIDEO


def vk_bot_instruction_video_path() -> Path:
    return VK_BOT_INSTRUCTION_VIDEO


def _public_url(public_path: str) -> str | None:
    from backend.config import get_urls

    web_url = get_urls().get("WEB_URL", "").rstrip("/")
    if not web_url:
        return None
    return f"{web_url}{public_path}"


def telegram_bot_instruction_public_url() -> str | None:
    return _public_url(TELEGRAM_BOT_INSTRUCTION_PUBLIC_PATH)


def vk_bot_instruction_public_url() -> str | None:
    return _public_url(VK_BOT_INSTRUCTION_PUBLIC_PATH)


def _cache_path() -> Path:
    configured = os.getenv("TUTORIAL_MEDIA_CACHE_PATH")
    if configured:
        return Path(configured)
    return PROJECT_ROOT / "logs" / _CACHE_FILENAME


def get_telegram_instruction_file_id() -> str | None:
    return get_instruction_file_id("telegram")


def save_telegram_instruction_file_id(file_id: str) -> None:
    save_instruction_file_id("telegram", file_id)


def get_instruction_file_id(kind: str) -> str | None:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    cache_key = _TELEGRAM_CACHE_KEYS.get(kind)
    if not cache_key:
        return None
    file_id = data.get(cache_key) if isinstance(data, dict) else None
    return file_id if isinstance(file_id, str) and file_id else None


def save_instruction_file_id(kind: str, file_id: str) -> None:
    if not file_id:
        return
    cache_key = _TELEGRAM_CACHE_KEYS.get(kind)
    if not cache_key:
        return
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (FileNotFoundError, OSError, ValueError):
        data = {}
    data[cache_key] = file_id
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
