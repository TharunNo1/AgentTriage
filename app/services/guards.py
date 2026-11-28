import json
import time
from typing import Any

from redis.asyncio import Redis

_PREFIX = "triage"


class RedisGuards:
    """Ephemeral, Redis-backed protections: mute windows, rate limits, idempotency. Never a source of truth."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def is_muted(self, fingerprint: str) -> bool:
        return bool(await self._redis.exists(f"{_PREFIX}:mute:{fingerprint}"))

    async def mute(self, fingerprint: str, seconds: int) -> None:
        await self._redis.set(f"{_PREFIX}:mute:{fingerprint}", 1, ex=seconds)

    async def allow_request(self, client: str, limit_per_minute: int) -> bool:
        """Count this request against the client's fixed minute window, including requests over the limit."""
        window = int(time.time() // 60)
        key = f"{_PREFIX}:rl:{client}:{window}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 120)
            count, _ = await pipe.execute()
        return int(count) <= limit_per_minute

    async def get_idempotent(self, client: str, key: str) -> dict[str, Any] | None:
        value = await self._redis.get(f"{_PREFIX}:idem:{client}:{key}")
        return json.loads(value) if value else None

    async def store_idempotent(self, client: str, key: str, response: dict[str, Any], ttl: int) -> None:
        await self._redis.set(f"{_PREFIX}:idem:{client}:{key}", json.dumps(response), ex=ttl)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())
