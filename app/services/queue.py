from datetime import timedelta
from typing import Any, Protocol

from arq.connections import ArqRedis


class JobQueue(Protocol):
    """Schedule workflow jobs by name, with optional deduplication keys and delayed delivery."""

    async def enqueue(self, job: str, *args: Any, job_id: str | None = None, defer_by: timedelta | None = None) -> None: ...


class ArqJobQueue:
    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue(self, job: str, *args: Any, job_id: str | None = None, defer_by: timedelta | None = None) -> None:
        await self._redis.enqueue_job(job, *args, _job_id=job_id, _defer_by=defer_by)
