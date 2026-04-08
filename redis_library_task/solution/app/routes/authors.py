"""
Роуты авторов.
С Redis-кэшем — справочник, меняется крайне редко.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с task/app/routes/authors.py ██
Добавлено: Cache-Aside для списка авторов и страницы автора.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Author
from app.cache_service import (                        # ← НОВОЕ
    get_cached_authors, set_cached_authors,
    get_cached_author, set_cached_author,
)

router = APIRouter(prefix="/authors", tags=["authors"])


@router.get("/")
async def list_authors(session: AsyncSession = Depends(get_session)):
    """
    Список всех авторов.

    Показывается в боковом меню, фильтрах, на главной.
    Данные меняются КРАЙНЕ РЕДКО (новый автор — раз в год).
    → Redis: TTL = 1 час.

    ██ ДОБАВЛЕН КЭШ (Cache-Aside): ██
    1. Проверяем Redis
    2. Если hit  → возвращаем из кэша (0 запросов к PostgreSQL)
    3. Если miss → идём в PostgreSQL → записываем в Redis
    """
    # ── НОВОЕ: проверяем кэш ──────────────────────────────
    cached = await get_cached_authors()
    if cached is not None:
        return cached
    # ──────────────────────────────────────────────────────

    result = await session.execute(
        select(Author).order_by(Author.id)
    )
    authors = result.scalars().all()
    data = [a.to_dict() for a in authors]

    # ── НОВОЕ: сохраняем в кэш ───────────────────────────
    await set_cached_authors(data)
    # ──────────────────────────────────────────────────────

    return data


@router.get("/{author_id}")
async def get_author(
    author_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Страница автора по ID.

    ██ ДОБАВЛЕН КЭШ (Cache-Aside): ██
    Данные автора одинаковы для всех, меняются крайне редко.
    Redis TTL = 1 час.
    """
    # ── НОВОЕ: проверяем кэш ──────────────────────────────
    cached = await get_cached_author(author_id)
    if cached is not None:
        return cached
    # ──────────────────────────────────────────────────────

    result = await session.execute(
        select(Author).where(Author.id == author_id)
    )
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(404, "Author not found")

    data = author.to_dict()

    # ── НОВОЕ: сохраняем в кэш ───────────────────────────
    await set_cached_author(author_id, data)
    # ──────────────────────────────────────────────────────

    return data
