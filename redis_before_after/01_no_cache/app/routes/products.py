"""
Роуты продуктов.
БЕЗ кэша — каждый запрос идёт в PostgreSQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_session
from app.models import Product
from app.schemas import ProductCreate, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


# ── READ endpoints ────────────────────────────────────────

@router.get("/")
async def list_products(
    category_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """
    Список товаров с пагинацией и фильтром по категории.

    Вызывается при просмотре каталога.
    Частота: ВЫСОКАЯ (каждая страница каталога).
    → Кандидат для кэша? ДА, но с осторожностью (пагинация!).
    """
    stmt = (
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.is_active.is_(True))
        .order_by(Product.id)
        .offset(offset)
        .limit(limit)
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)

    result = await session.execute(stmt)
    products = result.unique().scalars().all()
    return [p.to_dict() for p in products]


@router.get("/popular")
async def popular_products(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """
    Топ товаров по просмотрам.

    Показывается на ГЛАВНОЙ СТРАНИЦЕ каждому пользователю.
    Данные одинаковые для всех.
    Частота: ОЧЕНЬ ВЫСОКАЯ.
    → ЛУЧШИЙ кандидат для Redis-кэша.
    """
    result = await session.execute(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.is_active.is_(True))
        .order_by(Product.views_count.desc())
        .limit(limit)
    )
    products = result.unique().scalars().all()
    return [p.to_dict() for p in products]


@router.get("/count")
async def products_count(session: AsyncSession = Depends(get_session)):
    """Общее количество активных товаров."""
    result = await session.execute(
        select(func.count()).select_from(Product).where(Product.is_active.is_(True))
    )
    return {"count": result.scalar()}


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Карточка товара по ID.

    Вызывается при открытии страницы товара.
    Частота: ВЫСОКАЯ для популярных товаров.
    → Кандидат для кэша? ДА — особенно для горячих товаров.
    """
    result = await session.execute(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.id == product_id)
    )
    product = result.unique().scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    # Увеличиваем счётчик просмотров
    product.views_count += 1
    await session.commit()

    return product.to_dict()


# ── WRITE endpoints ───────────────────────────────────────

@router.post("/", status_code=201)
async def create_product(
    data: ProductCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Создать товар.

    Частота: НИЗКАЯ (админ-панель).
    → Кэшировать НЕ НУЖНО. Это операция записи.
    """
    product = Product(
        name=data.name,
        description=data.description,
        price=data.price,
        category_id=data.category_id,
    )
    session.add(product)
    await session.commit()
    await session.refresh(product, attribute_names=["category"])
    return product.to_dict()


@router.patch("/{product_id}")
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Обновить товар.

    Частота: НИЗКАЯ.
    → НЕ кэшировать. Но нужно инвалидировать кэш карточки.
    """
    result = await session.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await session.commit()
    await session.refresh(product, attribute_names=["category"])
    return product.to_dict()
