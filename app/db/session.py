from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Keep loaded attributes readable after commit so callers can build responses outside the transaction."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Commit on normal exit and roll back if the caller raises."""
    async with sessionmaker() as session, session.begin():
        yield session
