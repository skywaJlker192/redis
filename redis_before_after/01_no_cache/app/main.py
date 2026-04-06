"""
FastAPI приложение — чистый backend БЕЗ кэша.
Все запросы идут напрямую в PostgreSQL.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import categories, orders, products
from app.seed import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-12s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🗄️  Инициализация БД…")
    count = await seed_database()
    logger.info("✅ БД готова — %d товаров", count)
    yield


app = FastAPI(
    title="Shop API — без кэша",
    description="Чистый backend. Все запросы → PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(categories.router)
app.include_router(products.router)
app.include_router(orders.router)


@app.get("/health")
async def health():
    return {"status": "ok", "cache": "none"}
