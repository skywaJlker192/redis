"""
Cache Service — вся логика кэширования в одном месте.

НОВЫЙ ФАЙЛ — не существует в task/

Принцип: кэшируем ТОЛЬКО то, что:
  1. Читается ЧАСТО (горячие данные)
  2. Одинаково для ВСЕХ пользователей
  3. Меняется РЕДКО

НЕ кэшируем:
  - Операции записи (create, update, delete)
  - Персональные данные (конкретная выдача читателя)
  - Данные которые меняются постоянно (список выдач)
  - Поисковые запросы (слишком много комбинаций)

"""

from __future__ import annotations

import json
import logging
import random
from typing import Any

from app.redis_client import get_redis

logger = logging.getLogger("cache")

# ═══════════════════════════════════════════════════════════
# TTL конфигурация
# ═══════════════════════════════════════════════════════════

# Авторы почти не меняются → длинный TTL
AUTHORS_TTL = 3600          # 1 час
AUTHORS_JITTER = 600        # ±10 мин

# Топ-рейтинг — обновляется только при изменении рейтинга
TOP_RATED_TTL = 600         # 10 мин
TOP_RATED_JITTER = 120      # ±2 мин

# Популярные книги — views_count меняется чаще
POPULAR_TTL = 300           # 5 мин
POPULAR_JITTER = 60         # ±1 мин

# Карточка книги — средний TTL
BOOK_TTL = 600              # 10 мин
BOOK_JITTER = 120           # ±2 мин


def _ttl(base: int, jitter: int) -> int:
    """TTL + random jitter (защита от Cache Avalanche)."""
    return base + random.randint(0, jitter)


# ═══════════════════════════════════════════════════════════
# Ключи кэша
# ═══════════════════════════════════════════════════════════

def _key_authors() -> str:
    return "cache:authors:all"

def _key_author(author_id: int) -> str:
    return f"cache:author:{author_id}"

def _key_top_rated(limit: int) -> str:
    return f"cache:books:top-rated:{limit}"

def _key_popular(limit: int) -> str:
    return f"cache:books:popular:{limit}"

def _key_book(book_id: int) -> str:
    return f"cache:book:{book_id}"


# ═══════════════════════════════════════════════════════════
# Cache-Aside: базовые операции
# ═══════════════════════════════════════════════════════════

async def cache_get(key: str) -> Any | None:
    """Получить из кэша. None = cache miss."""
    r = await get_redis()
    raw = await r.get(key)
    if raw is None:
        logger.info("CACHE MISS   %s", key)
        return None
    logger.info("CACHE HIT    %s", key)
    return json.loads(raw)


async def cache_set(key: str, data: Any, ttl: int) -> None:
    """Записать в кэш с TTL."""
    r = await get_redis()
    await r.set(key, json.dumps(data, default=str), ex=ttl)
    logger.info("CACHE SET    %s  ttl=%d", key, ttl)


async def cache_delete(key: str) -> None:
    """Инвалидировать конкретный ключ."""
    r = await get_redis()
    await r.delete(key)
    logger.info("CACHE DELETE %s", key)


async def cache_delete_pattern(pattern: str) -> int:
    """Инвалидировать ключи по шаблону (SCAN)."""
    r = await get_redis()
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await r.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    logger.info("CACHE DELETE PATTERN %s  deleted=%d", pattern, deleted)
    return deleted


# ═══════════════════════════════════════════════════════════
# Высокоуровневые функции для каждого кэшируемого эндпоинта
# ═══════════════════════════════════════════════════════════

# ── Authors ──────────────────────────────────────────────

async def get_cached_authors() -> list[dict] | None:
    """Получить список авторов из кэша."""
    return await cache_get(_key_authors())


async def set_cached_authors(data: list[dict]) -> None:
    """Записать список авторов в кэш."""
    await cache_set(_key_authors(), data, _ttl(AUTHORS_TTL, AUTHORS_JITTER))


async def get_cached_author(author_id: int) -> dict | None:
    """Получить автора из кэша."""
    return await cache_get(_key_author(author_id))


async def set_cached_author(author_id: int, data: dict) -> None:
    """Записать автора в кэш."""
    await cache_set(_key_author(author_id), data, _ttl(AUTHORS_TTL, AUTHORS_JITTER))


# ── Books ────────────────────────────────────────────────

async def get_cached_top_rated(limit: int) -> list[dict] | None:
    """Получить топ книг по рейтингу из кэша."""
    return await cache_get(_key_top_rated(limit))


async def set_cached_top_rated(limit: int, data: list[dict]) -> None:
    """Записать топ книг по рейтингу в кэш."""
    await cache_set(_key_top_rated(limit), data, _ttl(TOP_RATED_TTL, TOP_RATED_JITTER))


async def get_cached_popular(limit: int) -> list[dict] | None:
    """Получить популярные книги из кэша."""
    return await cache_get(_key_popular(limit))


async def set_cached_popular(limit: int, data: list[dict]) -> None:
    """Записать популярные книги в кэш."""
    await cache_set(_key_popular(limit), data, _ttl(POPULAR_TTL, POPULAR_JITTER))


async def get_cached_book(book_id: int) -> dict | None:
    """Получить карточку книги из кэша."""
    return await cache_get(_key_book(book_id))


async def set_cached_book(book_id: int, data: dict) -> None:
    """Записать карточку книги в кэш."""
    await cache_set(_key_book(book_id), data, _ttl(BOOK_TTL, BOOK_JITTER))


# ── Инвалидация ──────────────────────────────────────────

async def invalidate_book(book_id: int) -> None:
    """Инвалидация при обновлении книги."""
    await cache_delete(_key_book(book_id))
    # Топ-рейтинг и популярные тоже могут измениться
    await cache_delete_pattern("cache:books:top-rated:*")
    await cache_delete_pattern("cache:books:popular:*")


async def invalidate_book_availability(book_id: int) -> None:
    """Инвалидация при выдаче/возврате книги (is_available меняется)."""
    await cache_delete(_key_book(book_id))
    # Топ-рейтинг и популярные могут показывать книги которые стали недоступны
    await cache_delete_pattern("cache:books:top-rated:*")
    await cache_delete_pattern("cache:books:popular:*")


async def invalidate_authors() -> None:
    """Инвалидация при изменении авторов."""
    await cache_delete(_key_authors())
    await cache_delete_pattern("cache:author:*")
