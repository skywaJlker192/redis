from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from app.db import get_session
from app.redis_client import get_redis
from app.cache_service import get_cached_authors, get_cached_author

router = APIRouter(prefix="/authors", tags=["authors"])

@router.get("/")
async def list_authors(redis: Redis = Depends(get_redis), session: AsyncSession = Depends(get_session)):
    return await get_cached_authors(redis, session)

@router.get("/{author_id}")
async def get_author(author_id: int, redis: Redis = Depends(get_redis), session: AsyncSession = Depends(get_session)):
    author = await get_cached_author(redis, author_id, session)
    if not author:
        from fastapi import HTTPException
        raise HTTPException(404, "Author not found")
    return author