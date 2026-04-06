"""
Seed — наполнение БД тестовыми данными.
"""

from __future__ import annotations

import random

from sqlalchemy import func, select

from app.db import async_session, engine
from app.models import Base, Category, Product

CATEGORIES = [
    ("Ноутбуки",     "laptops"),
    ("Смартфоны",    "phones"),
    ("Планшеты",     "tablets"),
    ("Аксессуары",   "accessories"),
    ("Мониторы",     "monitors"),
]

PRODUCTS_BY_CATEGORY = {
    "laptops": [
        ("MacBook Pro 16 M3 Max",     "Apple M3 Max, 36GB RAM, 1TB SSD",    3499.00),
        ("ThinkPad X1 Carbon Gen 11", "Intel i7-1365U, 32GB, 512GB",        1899.00),
        ("Dell XPS 15 9530",          "Intel i9-13900H, 64GB, 1TB",         2499.00),
        ("ASUS ROG Zephyrus G16",     "Intel i9, RTX 4090, 32GB",           2799.00),
        ("HP Spectre x360 14",        "Intel i7-1355U, 16GB, OLED",         1599.00),
    ],
    "phones": [
        ("iPhone 15 Pro Max",     "A17 Pro, 256GB, Titanium",     1199.00),
        ("Samsung Galaxy S24 Ultra", "Snapdragon 8 Gen 3, 512GB", 1299.00),
        ("Pixel 8 Pro",           "Tensor G3, 128GB",              899.00),
        ("OnePlus 12",            "Snapdragon 8 Gen 3, 256GB",    799.00),
        ("Xiaomi 14 Ultra",       "Snapdragon 8 Gen 3, 512GB",    999.00),
    ],
    "tablets": [
        ("iPad Pro 12.9 M2",     "M2 chip, 256GB, Liquid Retina XDR",   1099.00),
        ("Samsung Galaxy Tab S9", "Snapdragon 8 Gen 2, 256GB",           849.00),
        ("Surface Pro 9",         "Intel i7, 16GB, 256GB",               1599.00),
        ("Lenovo Tab P12 Pro",    "Snapdragon 870, OLED 12.6\"",         599.00),
    ],
    "accessories": [
        ("AirPods Pro 2 USB-C",   "Active Noise Cancellation, USB-C",  249.00),
        ("Logitech MX Master 3S", "Wireless mouse, 8K DPI",             99.00),
        ("Sony WH-1000XM5",       "Wireless ANC headphones",           349.00),
        ("Razer BlackWidow V4",   "Mechanical keyboard, RGB",          169.00),
        ("Apple Magic Keyboard",  "Touch ID, Numeric Keypad",          199.00),
        ("Samsung T7 Shield 2TB", "Portable SSD, USB 3.2",             159.00),
    ],
    "monitors": [
        ("Dell U2723QE",           "27\" 4K IPS, USB-C Hub",            619.00),
        ("LG 27GP950-B",          "27\" 4K 160Hz, Nano IPS, HDMI 2.1",  799.00),
        ("Samsung Odyssey G7 32", "32\" 1440p 240Hz, VA panel",          649.00),
        ("ASUS ProArt PA279CRV",  "27\" 4K IPS, 100% sRGB",            549.00),
    ],
}


async def seed_database() -> int:
    """Создать таблицы и заполнить тестовыми данными. Возвращает кол-во продуктов."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Уже есть данные?
        count = (await session.execute(select(func.count()).select_from(Product))).scalar() or 0
        if count > 0:
            return count

        # Создаём категории
        cat_map: dict[str, Category] = {}
        for name, slug in CATEGORIES:
            cat = Category(name=name, slug=slug)
            session.add(cat)
            cat_map[slug] = cat

        await session.flush()  # чтобы получить id категорий

        # Создаём продукты
        total = 0
        for slug, products_data in PRODUCTS_BY_CATEGORY.items():
            cat = cat_map[slug]
            for pname, desc, price in products_data:
                p = Product(
                    name=pname,
                    description=desc,
                    price=price,
                    category_id=cat.id,
                    is_active=True,
                    views_count=random.randint(0, 5000),
                )
                session.add(p)
                total += 1

        await session.commit()
        return total
