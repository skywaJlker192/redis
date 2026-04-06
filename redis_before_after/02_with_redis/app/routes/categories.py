"""
Роуты категорий.
С Redis-кэшем — данные меняются редко, читаются часто.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с 01_no_cache/app/routes/categories.py ██
Добавлено: cache_get → cache_set (Cache-Aside паттерн)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Category
from app.cache_service import get_cached_categories, set_cached_categories  # ← НОВОЕ

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/")
async def list_categories(session: AsyncSession = Depends(get_session)):
    """
    Список всех категорий.

    Вызывается на каждой странице магазина (меню, фильтры).
    Данные меняются ОЧЕНЬ РЕДКО (раз в месяц).
    → Redis: TTL = 1 час.

    ██ ДОБАВЛЕН КЭШ (Cache-Aside): ██
    1. Проверяем Redis
    2. Если hit  → возвращаем из кэша (0 запросов к PostgreSQL)
    3. Если miss → идём в PostgreSQL → записываем в Redis
    """
    # ── НОВОЕ: проверяем кэш ──────────────────────────────
    cached = await get_cached_categories()
    if cached is not None:
        return cached  # ← 0 нагрузки на PostgreSQL!
    # ──────────────────────────────────────────────────────

    # Оригинальная логика (как в 01_no_cache)
    result = await session.execute(
        select(Category).order_by(Category.id)
    )
    categories = result.scalars().all()
    data = [c.to_dict() for c in categories]

    # ── НОВОЕ: сохраняем в кэш ───────────────────────────
    await set_cached_categories(data)
    # ──────────────────────────────────────────────────────

    return data
