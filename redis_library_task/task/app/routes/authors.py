"""
Роуты авторов.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Author

router = APIRouter(prefix="/authors", tags=["authors"])


@router.get("/")
async def list_authors(session: AsyncSession = Depends(get_session)):
    """Список всех авторов."""
    result = await session.execute(
        select(Author).order_by(Author.id)
    )
    authors = result.scalars().all()
    return [a.to_dict() for a in authors]


@router.get("/{author_id}")
async def get_author(
    author_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Страница автора по ID."""
    from fastapi import HTTPException

    result = await session.execute(
        select(Author).where(Author.id == author_id)
    )
    author = result.scalar_one_or_none()
    if not author:
        raise HTTPException(404, "Author not found")
    return author.to_dict()
