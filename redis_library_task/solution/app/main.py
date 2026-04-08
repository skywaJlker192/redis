"""
FastAPI приложение — онлайн-библиотека С Redis-кэшированием.

██ ИЗМЕНЁННЫЙ ФАЙЛ — сравни с task/app/main.py ██
Добавлено: подключение Redis в lifespan, health check Redis.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import authors, books, borrowings
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
    logger.info("✅ БД готова — %d книг", count)

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
    title="Library API — с Redis-кэшем",
    description="Тот же backend, но горячие эндпоинты кэшируются в Redis.",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(authors.router)
app.include_router(books.router)
app.include_router(borrowings.router)


@app.get("/health")
async def health():
    r = await get_redis()
    redis_ok = await r.ping()
    return {"status": "ok", "cache": "redis", "redis_connected": redis_ok}
