"""
Pydantic-схемы для валидации запросов и ответов.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Category ──────────────────────────────────────────────

class CategoryRead(BaseModel):
    id: int
    name: str
    slug: str
    model_config = {"from_attributes": True}


# ── Product ───────────────────────────────────────────────

class ProductRead(BaseModel):
    id: int
    name: str
    description: str
    price: float
    category_id: int
    category_name: str | None = None
    is_active: bool
    views_count: int
    created_at: str | None = None


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    price: float = Field(..., gt=0)
    category_id: int


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = Field(None, gt=0)
    category_id: int | None = None
    is_active: bool | None = None


# ── Order ─────────────────────────────────────────────────

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1)


class OrderCreate(BaseModel):
    customer_name: str = Field(..., min_length=1)
    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemRead(BaseModel):
    id: int
    product_id: int
    product_name: str | None = None
    quantity: int
    price: float


class OrderRead(BaseModel):
    id: int
    customer_name: str
    total: float
    created_at: str | None = None
    items: list[OrderItemRead] = []
