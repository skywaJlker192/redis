"""
Cache Service — вся логика кэширования в одном месте.

██ НОВЫЙ ФАЙЛ — не существует в 01_no_cache ██

Принцип: кэшируем ТОЛЬКО то, что:
  1. Читается ЧАСТО (горячие данные)
  2. Одинаково для ВСЕХ пользователей
  3. Меняется РЕДКО

НЕ кэшируем:
  - Операции записи (create, update, delete)
  - Персональные данные (конкретный заказ пользователя)
  - Данные которые меняются постоянно (список заказов)

┌──────────────────────────────────────────────────────────┐
│  Эндпоинт              │ Кэш?  │ Почему                 │
├────────────────────────-┼───────┼────────────────────────┤
│ GET /categories/        │  ✅   │ Редко меняется         │
│ GET /products/popular   │  ✅   │ Главная страница       │
│ GET /products/{id}      │  ✅   │ Карточка товара        │
│ GET /products/          │  ❌   │ Пагинация, много       │
│ GET /products/count     │  ❌   │ Быстрый запрос, мало   │
│ POST /products/         │  ❌   │ Запись                 │
│ PATCH /products/{id}    │  ❌   │ Запись (+ инвалидация) │
│ POST /orders/           │  ❌   │ Запись, уникальные     │
│ GET /orders/            │  ❌   │ Постоянно меняется     │
│ GET /orders/{id}        │  ❌   │ Персональные данные    │
└──────────────────────────────────────────────────────────┘
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

# Категории почти не меняются → длинный TTL
CATEGORIES_TTL = 3600       # 1 час
CATEGORIES_JITTER = 600     # ±10 мин

# Популярные товары — обновляем чаще
POPULAR_TTL = 300           # 5 мин
POPULAR_JITTER = 60         # ±1 мин

# Карточка товара — средний TTL
PRODUCT_TTL = 600           # 10 мин
PRODUCT_JITTER = 120        # ±2 мин


def _ttl(base: int, jitter: int) -> int:
    """TTL + random jitter (защита от Cache Avalanche)."""
    return base + random.randint(0, jitter)


# ═══════════════════════════════════════════════════════════
# Ключи кэша
# ═══════════════════════════════════════════════════════════

def _key_categories() -> str:
    return "cache:categories:all"

def _key_popular(limit: int) -> str:
    return f"cache:products:popular:{limit}"

def _key_product(product_id: int) -> str:
    return f"cache:product:{product_id}"


# ═══════════════════════════════════════════════════════════
# Cache-Aside: GET (проверить кэш → если miss → вызвать fallback → записать)
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

async def get_cached_categories() -> list[dict] | None:
    """Получить категории из кэша."""
    return await cache_get(_key_categories())


async def set_cached_categories(data: list[dict]) -> None:
    """Записать категории в кэш."""
    await cache_set(_key_categories(), data, _ttl(CATEGORIES_TTL, CATEGORIES_JITTER))


async def get_cached_popular(limit: int) -> list[dict] | None:
    """Получить популярные товары из кэша."""
    return await cache_get(_key_popular(limit))


async def set_cached_popular(limit: int, data: list[dict]) -> None:
    """Записать популярные товары в кэш."""
    await cache_set(_key_popular(limit), data, _ttl(POPULAR_TTL, POPULAR_JITTER))


async def get_cached_product(product_id: int) -> dict | None:
    """Получить карточку товара из кэша."""
    return await cache_get(_key_product(product_id))


async def set_cached_product(product_id: int, data: dict) -> None:
    """Записать карточку товара в кэш."""
    await cache_set(_key_product(product_id), data, _ttl(PRODUCT_TTL, PRODUCT_JITTER))


# ── Инвалидация ──────────────────────────────────────────

async def invalidate_product(product_id: int) -> None:
    """Инвалидация при обновлении товара."""
    await cache_delete(_key_product(product_id))
    # Популярные товары тоже могут измениться
    await cache_delete_pattern("cache:products:popular:*")


async def invalidate_categories() -> None:
    """Инвалидация при изменении категорий."""
    await cache_delete(_key_categories())
