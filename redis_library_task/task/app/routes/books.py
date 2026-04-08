"""
Роуты книг.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_session
from app.models import Book
from app.schemas import BookCreate, BookUpdate

router = APIRouter(prefix="/books", tags=["books"])


# ── READ endpoints ────────────────────────────────────────

@router.get("/")
async def list_books(
    author_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Список книг с пагинацией и фильтром по автору."""
    stmt = (
        select(Book)
        .options(joinedload(Book.author))
        .where(Book.is_available.is_(True))
        .order_by(Book.id)
        .offset(offset)
        .limit(limit)
    )
    if author_id:
        stmt = stmt.where(Book.author_id == author_id)

    result = await session.execute(stmt)
    books = result.unique().scalars().all()
    return [b.to_dict() for b in books]


@router.get("/top-rated")
async def top_rated_books(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Топ книг по рейтингу."""
    result = await session.execute(
        select(Book)
        .options(joinedload(Book.author))
        .where(Book.is_available.is_(True))
        .order_by(Book.rating.desc())
        .limit(limit)
    )
    books = result.unique().scalars().all()
    return [b.to_dict() for b in books]


@router.get("/popular")
async def popular_books(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Самые просматриваемые книги (по views_count)."""
    result = await session.execute(
        select(Book)
        .options(joinedload(Book.author))
        .where(Book.is_available.is_(True))
        .order_by(Book.views_count.desc())
        .limit(limit)
    )
    books = result.unique().scalars().all()
    return [b.to_dict() for b in books]


@router.get("/count")
async def books_count(session: AsyncSession = Depends(get_session)):
    """Общее количество доступных книг."""
    result = await session.execute(
        select(func.count()).select_from(Book).where(Book.is_available.is_(True))
    )
    return {"count": result.scalar()}


@router.get("/search")
async def search_books(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Поиск книг по названию."""
    result = await session.execute(
        select(Book)
        .options(joinedload(Book.author))
        .where(Book.title.ilike(f"%{q}%"))
        .order_by(Book.rating.desc())
        .limit(limit)
    )
    books = result.unique().scalars().all()
    return [b.to_dict() for b in books]


@router.get("/{book_id}")
async def get_book(
    book_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Карточка книги по ID."""
    result = await session.execute(
        select(Book)
        .options(joinedload(Book.author))
        .where(Book.id == book_id)
    )
    book = result.unique().scalar_one_or_none()
    if not book:
        raise HTTPException(404, "Book not found")

    # Увеличиваем счётчик просмотров
    book.views_count += 1
    await session.commit()

    return book.to_dict()


# ── WRITE endpoints ───────────────────────────────────────

@router.post("/", status_code=201)
async def create_book(
    data: BookCreate,
    session: AsyncSession = Depends(get_session),
):
    """Добавить книгу."""
    book = Book(
        title=data.title,
        description=data.description,
        isbn=data.isbn,
        author_id=data.author_id,
        year=data.year,
        rating=data.rating,
    )
    session.add(book)
    await session.commit()
    await session.refresh(book, attribute_names=["author"])
    return book.to_dict()


@router.patch("/{book_id}")
async def update_book(
    book_id: int,
    data: BookUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Обновить книгу."""
    result = await session.execute(
        select(Book).where(Book.id == book_id)
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(404, "Book not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)

    await session.commit()
    await session.refresh(book, attribute_names=["author"])
    return book.to_dict()
