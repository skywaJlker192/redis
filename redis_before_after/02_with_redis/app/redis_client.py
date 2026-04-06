"""
Redis-клиент — async singleton.

██ НОВЫЙ ФАЙЛ — не существует в 01_no_cache ██

Подключение к Redis. Используется только cache_service.py.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Создать или вернуть пул подключений к Redis."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


async def close_redis() -> None:
    """Закрыть пул при shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
