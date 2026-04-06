"""
Роуты категорий.
БЕЗ кэша — каждый запрос идёт в PostgreSQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Category

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/")
async def list_categories(session: AsyncSession = Depends(get_session)):
    """
    Список всех категорий.

    Вызывается на каждой странице магазина (меню, фильтры).
    Данные меняются ОЧЕНЬ РЕДКО (раз в месяц).
    → ИДЕАЛЬНЫЙ кандидат для Redis-кэша.
    """
    result = await session.execute(
        select(Category).order_by(Category.id)
    )
    categories = result.scalars().all()
    return [c.to_dict() for c in categories]
