import redis.asyncio as aioredis
from app.config import settings

class RedisClient:
    _client = None

    @classmethod
    async def get_client(cls):
        if cls._client is None:
            cls._client = aioredis.from_url(settings.redis_url, decode_responses=False)
        return cls._client

async def get_redis():
    return await RedisClient.get_client()

async def close_redis():
    if RedisClient._client:
        await RedisClient._client.aclose()
        RedisClient._client = None