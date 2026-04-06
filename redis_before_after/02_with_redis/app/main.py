"""
FastAPI приложение — backend С Redis-кэшированием.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с 01_no_cache/app/main.py ██
Добавлено: подключение Redis в lifespan, health check Redis.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import categories, orders, products
from app.seed import seed_database
from app.redis_client import get_redis, close_redis   # ← НОВОЕ

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

    # ── НОВОЕ: подключение Redis ──────────────────────────
    logger.info("🔴 Подключение к Redis…")
    await get_redis()
    logger.info("✅ Redis подключён")
    # ──────────────────────────────────────────────────────

    yield

    # ── НОВОЕ: отключение Redis ───────────────────────────
    await close_redis()
    logger.info("🛑 Redis отключён")
    # ──────────────────────────────────────────────────────


app = FastAPI(
    title="Shop API — с Redis-кэшем",
    description="Тот же backend, но горячие эндпоинты кэшируются в Redis.",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(categories.router)
app.include_router(products.router)
app.include_router(orders.router)


@app.get("/health")
async def health():
    # ── НОВОЕ: проверка Redis в health check ──────────────
    r = await get_redis()
    redis_ok = await r.ping()
    return {"status": "ok", "cache": "redis", "redis": redis_ok}
    # ──────────────────────────────────────────────────────
