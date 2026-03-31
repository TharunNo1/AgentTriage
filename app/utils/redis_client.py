import redis.asyncio as redis
from app.config import settings

def create_redis_client():
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        max_connections=10
    )
