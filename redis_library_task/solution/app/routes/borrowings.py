"""
Роуты выдачи книг.
БЕЗ кэша — каждый запрос идёт в PostgreSQL.
Но при выдаче/возврате книги — ИНВАЛИДАЦИЯ кэша карточки книги.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с task/app/routes/borrowings.py ██
Добавлено: инвалидация кэша книги при выдаче и возврате.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_session
from app.models import Book, Borrowing
from app.schemas import BorrowingCreate

# ── НОВОЕ: импорт инвалидации ────────────────────────────
from app.cache_service import invalidate_book_availability
# ──────────────────────────────────────────────────────────

router = APIRouter(prefix="/borrowings", tags=["borrowings"])


@router.post("/", status_code=201)
async def create_borrowing(
    data: BorrowingCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Выдать книгу читателю.

    ██ БЕЗ КЭША, НО С ИНВАЛИДАЦИЕЙ ██
    КАЖДАЯ выдача уникальна. Но меняем is_available у книги →
    нужно инвалидировать кэш карточки книги.
    """
    result = await session.execute(
        select(Book).where(Book.id == data.book_id)
    )
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(404, f"Book {data.book_id} not found")
    if not book.is_available:
        raise HTTPException(400, f"Book '{book.title}' is not available")

    book.is_available = False

    borrowing = Borrowing(
        reader_name=data.reader_name,
        book_id=data.book_id,
    )
    session.add(borrowing)
    await session.commit()

    # ── НОВОЕ: инвалидация кэша книги (is_available изменился) ──
    await invalidate_book_availability(data.book_id)
    # ────────────────────────────────────────────────────────────

    result = await session.execute(
        select(Borrowing)
        .options(joinedload(Borrowing.book))
        .where(Borrowing.id == borrowing.id)
    )
    borrowing = result.unique().scalar_one()
    return borrowing.to_dict()


@router.post("/{borrowing_id}/return", status_code=200)
async def return_book(
    borrowing_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Вернуть книгу.

    ██ БЕЗ КЭША, НО С ИНВАЛИДАЦИЕЙ ██
    Операция записи — меняем borrowing и доступность книги.
    """
    result = await session.execute(
        select(Borrowing)
        .options(joinedload(Borrowing.book))
        .where(Borrowing.id == borrowing_id)
    )
    borrowing = result.unique().scalar_one_or_none()
    if not borrowing:
        raise HTTPException(404, "Borrowing not found")
    if borrowing.is_returned:
        raise HTTPException(400, "Book already returned")

    borrowing.is_returned = True
    borrowing.returned_at = datetime.datetime.now(datetime.UTC)

    result = await session.execute(
        select(Book).where(Book.id == borrowing.book_id)
    )
    book = result.scalar_one()
    book.is_available = True

    await session.commit()

    # ── НОВОЕ: инвалидация кэша книги (is_available изменился) ──
    await invalidate_book_availability(borrowing.book_id)
    # ────────────────────────────────────────────────────────────

    return borrowing.to_dict()


@router.get("/")
async def list_borrowings(
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    """
    Список выдач (для библиотекаря).

    ██ БЕЗ КЭША ██
    Почему: данные постоянно меняются (новые выдачи, возвраты).
    Кэш будет инвалидирован практически сразу.
    """
    stmt = (
        select(Borrowing)
        .options(joinedload(Borrowing.book))
        .order_by(Borrowing.borrowed_at.desc())
        .limit(limit)
    )
    if active_only:
        stmt = stmt.where(Borrowing.is_returned.is_(False))

    result = await session.execute(stmt)
    borrowings = result.unique().scalars().all()
    return [b.to_dict() for b in borrowings]


@router.get("/{borrowing_id}")
async def get_borrowing(
    borrowing_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Получить выдачу по ID.

    ██ БЕЗ КЭША ██
    Почему: персональные данные, запрашиваются конкретным
    читателем/библиотекарем. Нет повторных запросов.
    """
    result = await session.execute(
        select(Borrowing)
        .options(joinedload(Borrowing.book))
        .where(Borrowing.id == borrowing_id)
    )
    borrowing = result.unique().scalar_one_or_none()
    if not borrowing:
        raise HTTPException(404, "Borrowing not found")
    return borrowing.to_dict()
