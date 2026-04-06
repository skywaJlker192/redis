"""
Роуты заказов.
БЕЗ кэша — и НЕ НУЖНО кэшировать.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db import get_session
from app.models import Order, OrderItem, Product
from app.schemas import OrderCreate

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", status_code=201)
async def create_order(
    data: OrderCreate,
    session: AsyncSession = Depends(get_session),
):
    """
    Создать заказ.

    КАЖДЫЙ заказ уникален. Данные постоянно пишутся.
    → Кэшировать НЕЛЬЗЯ. Это write-heavy операция.
    """
    order = Order(customer_name=data.customer_name, total=0)
    session.add(order)
    await session.flush()

    total = 0.0
    for item_data in data.items:
        # Получаем товар для цены
        result = await session.execute(
            select(Product).where(Product.id == item_data.product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(404, f"Product {item_data.product_id} not found")

        item = OrderItem(
            order_id=order.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
            price=product.price,
        )
        session.add(item)
        total += product.price * item_data.quantity

    order.total = round(total, 2)
    await session.commit()

    # Загружаем с items для ответа
    result = await session.execute(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order.id)
    )
    order = result.unique().scalar_one()
    return order.to_dict()


@router.get("/")
async def list_orders(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """
    Список заказов (для админ-панели).

    Каждый запрос — актуальные данные.
    → НЕ кэшировать: данные постоянно меняются.
    """
    result = await session.execute(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    orders = result.unique().scalars().all()
    return [o.to_dict() for o in orders]


@router.get("/{order_id}")
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Получить заказ по ID.

    Запрашивается КОНКРЕТНЫМ пользователем ОДИН раз.
    → НЕ кэшировать: персональные данные, нет повторных запросов.
    """
    result = await session.execute(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order_id)
    )
    order = result.unique().scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return order.to_dict()
