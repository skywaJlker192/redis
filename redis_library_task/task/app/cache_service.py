import json
import random
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Author, Book

# Базовые операции
async def cache_get(redis: Redis, key: str):
    data = await redis.get(key)
    return json.loads(data) if data else None

async def cache_set(redis: Redis, key: str, value, ttl: int):
    await redis.set(key, json.dumps(value), ex=ttl)

async def cache_delete(redis: Redis, *keys):
    if keys:
        await redis.delete(*keys)

def ttl_with_jitter(base: int, jitter: int = 30):
    return base + random.randint(0, jitter)

# Кэшированные функции
async def get_cached_authors(redis: Redis, session: AsyncSession):
    key = "authors:list"
    if (data := await cache_get(redis, key)) is not None:
        return data
    result = await session.execute(select(Author).order_by(Author.id))
    authors = [a.to_dict() for a in result.scalars()]
    await cache_set(redis, key, authors, ttl_with_jitter(3600))
    return authors

async def get_cached_author(redis: Redis, author_id: int, session: AsyncSession):
    key = f"author:{author_id}"
    if (data := await cache_get(redis, key)) is not None:
        return data
    result = await session.execute(select(Author).where(Author.id == author_id))
    author = result.scalar_one_or_none()
    if not author: return None
    data = author.to_dict()
    await cache_set(redis, key, data, ttl_with_jitter(3600))
    return data

async def get_cached_book(redis: Redis, book_id: int, session: AsyncSession):
    key = f"book:{book_id}"
    if (data := await cache_get(redis, key)) is not None:
        return data
    result = await session.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book: return None
    data = book.to_dict()
    await cache_set(redis, key, data, ttl_with_jitter(600))
    return data

async def get_cached_top_rated(redis: Redis, session: AsyncSession):
    key = "books:top-rated"
    if (data := await cache_get(redis, key)) is not None:
        return data
    # Здесь логика из твоего роута top-rated
    result = await session.execute(select(Book).order_by(Book.rating.desc()).limit(10))
    books = [b.to_dict() for b in result.scalars()]
    await cache_set(redis, key, books, ttl_with_jitter(300))
    return books

async def get_cached_popular(redis: Redis, session: AsyncSession):
    key = "books:popular"
    if (data := await cache_get(redis, key)) is not None:
        return data
    result = await session.execute(select(Book).order_by(Book.borrow_count.desc()).limit(10))
    books = [b.to_dict() for b in result.scalars()]
    await cache_set(redis, key, books, ttl_with_jitter(300))
    return books

async def get_cached_books_count(redis: Redis, session: AsyncSession):
    key = "books:count"
    if (data := await cache_get(redis, key)) is not None:
        return data
    count = await session.scalar(select(Book).count())
    await cache_set(redis, key, count, ttl_with_jitter(60))
    return count

# Инвалидация
async def invalidate_book_cache(redis: Redis, book_id=None):
    keys = ["books:top-rated", "books:popular", "books:count"]
    if book_id:
        keys.append(f"book:{book_id}")
    await cache_delete(redis, *keys)