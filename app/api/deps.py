from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.services.guards import RedisGuards
from app.services.ingest import IngestService
from app.services.workflow import Workflow


@dataclass(slots=True)
class Container:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    guards: RedisGuards
    ingest: IngestService
    workflow: Workflow


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
