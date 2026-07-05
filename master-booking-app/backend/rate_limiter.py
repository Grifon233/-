"""
Rate limit с Redis и fallback на in-memory storage.

В production с несколькими workers использует Redis.
Если Redis недоступен — in-memory (работает только для одного worker).
"""
import ipaddress
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Максимум запросов в окне
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # секунд
# Защита от безграничного роста in-memory словаря.
_MAX_TRACKED_KEYS = 10000


def client_ip_from_request(request) -> str:
    """Реальный IP клиента.

    За nginx request.client.host — это адрес прокси (один на всех), поэтому
    лимит применялся бы ко всем клиентам сразу. Берём X-Forwarded-For, но
    доверяем ему только если непосредственный пир — локальный/приватный
    (наш nginx), чтобы внешний клиент не мог подделать заголовок.
    """
    peer = request.client.host if request.client else None
    xff = request.headers.get("x-forwarded-for")
    if xff and peer:
        try:
            addr = ipaddress.ip_address(peer)
            if addr.is_private or addr.is_loopback:
                forwarded = xff.split(",")[0].strip()
                if forwarded:
                    return forwarded
        except ValueError:
            pass
    return peer or "unknown"


class InMemoryRateStore:
    """Fallback — хранение в памяти процесса."""

    def __init__(self):
        self._store: dict[str, list[datetime]] = {}

    async def check_and_increment(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)

        bucket = [t for t in self._store.get(key, []) if t > window_start]

        if len(bucket) >= RATE_LIMIT_REQUESTS:
            self._store[key] = bucket
            return False

        bucket.append(now)
        self._store[key] = bucket

        # Периодически выбрасываем неактивные ключи, чтобы словарь не рос вечно.
        if len(self._store) > _MAX_TRACKED_KEYS:
            self._store = {
                k: v for k, v in self._store.items() if v and v[-1] > window_start
            }
        return True


class RedisRateStore:
    """Production — Redis через redis-py."""

    def __init__(self):
        self._redis: Optional = None
        self._connected = False

    async def _ensure_connected(self):
        if self._connected and self._redis:
            try:
                await self._redis.ping()
                return
            except Exception:
                self._connected = False

        try:
            import redis.asyncio as aioredis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis for rate limiting")
        except Exception as e:
            logger.warning(f"Redis unavailable, rate limit will be per-process: {e}")
            self._connected = False
            self._redis = None

    async def check_and_increment(self, key: str) -> bool:
        await self._ensure_connected()
        if not self._connected or not self._redis:
            return True  # fail open — без Redis не блокируем

        try:
            window_key = f"ratelimit:{key}"
            current = await self._redis.get(window_key)
            if current and int(current) >= RATE_LIMIT_REQUESTS:
                return False

            pipe = self._redis.pipeline()
            pipe.incr(window_key)
            pipe.expire(window_key, RATE_LIMIT_WINDOW)
            await pipe.execute()
            return True
        except Exception as e:
            logger.warning(f"Rate limit check error: {e}")
            return True


class RateLimiter:
    """Единый интерфейс rate limiter."""

    def __init__(self):
        self._redis_store = RedisRateStore()
        self._memory_store = InMemoryRateStore()
        self._use_redis = os.getenv("REDIS_URL") is not None

    async def check(self, client_ip: str) -> bool:
        if self._use_redis:
            return await self._redis_store.check_and_increment(client_ip)
        return await self._memory_store.check_and_increment(client_ip)


rate_limiter = RateLimiter()
