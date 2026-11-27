import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.api.auth import hash_api_key
from app.api.deps import Container
from app.api.main import create_app
from app.core.settings import Settings
from app.db.models import ApiClient
from app.db.session import create_engine, create_sessionmaker, transaction
from app.integrations.registry import build_integrations
from app.services.guards import RedisGuards
from app.services.ingest import IngestService
from app.services.workflow import Workflow

pytestmark = pytest.mark.integration

HMAC_SECRET = "integration-secret"
INGEST_KEY = "atk_ingest_test_key"
OPERATOR_KEY = "atk_operator_test_key"


@dataclass
class Job:
    name: str
    args: tuple[Any, ...]
    job_id: str | None
    defer_by: timedelta | None


@dataclass
class FakeQueue:
    """Records jobs instead of using arq; deduplicates on job_id like arq does."""

    jobs: list[Job] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    async def enqueue(self, job: str, *args: Any, job_id: str | None = None, defer_by: timedelta | None = None) -> None:
        if job_id is not None:
            if job_id in self.seen:
                return
            self.seen.add(job_id)
        self.jobs.append(Job(job, args, job_id, defer_by))

    def names(self) -> list[str]:
        return [j.name for j in self.jobs]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def settings(postgres_url: str, redis_url: str) -> Settings:
    return Settings(
        env="test",
        log_json=False,
        database_url=postgres_url,  # type: ignore[arg-type]
        redis_url=redis_url,  # type: ignore[arg-type]
        webhook_hmac_secrets={"alertmanager-hmac": HMAC_SECRET},  # type: ignore[dict-item]
        rate_limit_per_minute=10_000,
    )


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture(scope="session")
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(str(settings.redis_url))
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
async def _clean(engine: AsyncEngine, redis: Redis, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE incidents, alert_signals, incident_events, remediation_actions, approvals, agent_runs, api_clients "
                "RESTART IDENTITY CASCADE"
            )
        )
    await redis.flushdb()
    async with transaction(sessionmaker) as session:
        session.add(ApiClient(name="ingest-client", key_hash=hash_api_key(INGEST_KEY), scopes=["ingest"], active=True))
        session.add(ApiClient(name="alice", key_hash=hash_api_key(OPERATOR_KEY), scopes=["operator"], active=True))


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def container(settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis, queue: FakeQueue) -> Container:
    guards = RedisGuards(redis)
    return Container(
        settings=settings,
        sessionmaker=sessionmaker,
        guards=guards,
        ingest=IngestService(sessionmaker, guards, queue),
        workflow=Workflow(sessionmaker, queue, guards, build_integrations(settings), settings),
    )


@pytest.fixture
async def client(settings: Settings, container: Container) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    app.state.container = container
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


class Worker:
    """Runs queued jobs in-process against the real Workflow, in enqueue order."""

    def __init__(self, container: Container, queue: FakeQueue) -> None:
        self.wf = container.workflow
        self.queue = queue
        self.done = 0

    async def drain(self, *, skip: tuple[str, ...] = ("expire_approval",)) -> list[str]:
        """Run queued work immediately, leaving approval expiry for tests that explicitly trigger it."""
        ran: list[str] = []
        while self.done < len(self.queue.jobs):
            job = self.queue.jobs[self.done]
            self.done += 1
            if job.name in skip:
                continue
            await self.run(job)
            ran.append(job.name)
        return ran

    async def run(self, job: Job) -> None:
        a = job.args
        match job.name:
            case "triage_incident":
                await self.wf.triage(uuid.UUID(a[0]), *a[1:])
            case "execute_remediation":
                await self.wf.execute_remediation(uuid.UUID(a[0]))
            case "verify_remediation":
                await self.wf.verify_remediation(uuid.UUID(a[0]))
            case "expire_approval":
                await self.wf.expire_approval(uuid.UUID(a[0]))
            case "sync_ticket":
                await self.wf.sync_ticket(uuid.UUID(a[0]))
            case "send_notification":
                await self.wf.send_notification(uuid.UUID(a[0]), a[1])
            case _:
                raise AssertionError(f"unknown job {job.name}")


@pytest.fixture
def worker(container: Container, queue: FakeQueue) -> Worker:
    return Worker(container, queue)
