import logging
import os

from aiogram.fsm.storage.memory import MemoryStorage


logger = logging.getLogger(__name__)


def create_fsm_storage():
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        logger.warning(
            "REDIS_URL is not configured; Telegram dialog state will reset after a process restart"
        )
        return MemoryStorage()

    from aiogram.fsm.storage.redis import RedisStorage

    logger.info("Using Redis for persistent Telegram dialog state")
    return RedisStorage.from_url(redis_url)
