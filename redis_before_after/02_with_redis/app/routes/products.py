"""
Роуты продуктов.
С Redis-кэшем на ГОРЯЧИХ эндпоинтах.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с 01_no_cache/app/routes/products.py ██

Кэш добавлен ТОЛЬКО на:
  • GET /products/popular  — главная страница, все пользователи видят одно и то же
  • GET /products/{id}     — карточка товара, популярные товары запрашиваются часто

Кэш НЕ добавлен на:
  • GET /products/         — пагинация создаёт слишком много комбинаций ключей
  • GET /products/count    — лёгкий запрос, кэш не оправдан
  • POST /products/        — операция записи
  • PATCH /products/{id}   — операция записи (но добавлена ИНВАЛИДАЦИЯ кэша!)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_session
from app.models import Product
from app.schemas import ProductCreate, ProductUpdate

# ── НОВОЕ: импорт кэш-функций ────────────────────────────
from app.cache_service import (
    get_cached_popular,
    set_cached_popular,
    get_cached_product,
    set_cached_product,
    invalidate_product,
)
# ──────────────────────────────────────────────────────────

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

    ██ БЕЗ КЭША ██
    Почему: комбинации category_id × limit × offset создают
    слишком много уникальных ключей. Кэш будет неэффективным
    (низкий hit rate, много памяти).
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

    ██ ДОБАВЛЕН КЭШ (Cache-Aside): ██
    Показывается на ГЛАВНОЙ СТРАНИЦЕ — самый горячий эндпоинт.
    Одинаковый ответ для всех → идеальный кандидат.
    Redis TTL = 5 мин.
    """
    # ── НОВОЕ: проверяем кэш ──────────────────────────────
    cached = await get_cached_popular(limit)
    if cached is not None:
        return cached
    # ──────────────────────────────────────────────────────

    result = await session.execute(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.is_active.is_(True))
        .order_by(Product.views_count.desc())
        .limit(limit)
    )
    products = result.unique().scalars().all()
    data = [p.to_dict() for p in products]

    # ── НОВОЕ: сохраняем в кэш ───────────────────────────
    await set_cached_popular(limit, data)
    # ──────────────────────────────────────────────────────

    return data


@router.get("/count")
async def products_count(session: AsyncSession = Depends(get_session)):
    """
    Общее количество активных товаров.

    ██ БЕЗ КЭША ██
    Почему: запрос COUNT(*) очень быстрый в PostgreSQL,
    кэширование не даст заметного выигрыша.
    """
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

    ██ ДОБАВЛЕН КЭШ (Cache-Aside): ██
    Популярные товары запрашиваются тысячами пользователей.
    Redis TTL = 10 мин.
    """
    # ── НОВОЕ: проверяем кэш ──────────────────────────────
    cached = await get_cached_product(product_id)
    if cached is not None:
        return cached
    # ──────────────────────────────────────────────────────

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

    data = product.to_dict()

    # ── НОВОЕ: сохраняем в кэш ───────────────────────────
    await set_cached_product(product_id, data)
    # ──────────────────────────────────────────────────────

    return data


# ── WRITE endpoints ───────────────────────────────────────

@router.post("/", status_code=201)
async def create_product(
    data: ProductCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Создать товар.

    ██ БЕЗ КЭША ██ — операция записи.
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

    ██ БЕЗ КЭША, НО С ИНВАЛИДАЦИЕЙ ██
    После обновления в БД нужно удалить старый кэш,
    иначе пользователи увидят устаревшие данные.
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

    # ── НОВОЕ: инвалидация кэша после записи ─────────────
    await invalidate_product(product_id)
    # ──────────────────────────────────────────────────────

    return product.to_dict()
