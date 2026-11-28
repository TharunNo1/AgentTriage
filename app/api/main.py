import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.deps import Container
from app.api.routers import alerts, dashboard, health, incidents
from app.core.errors import DomainError
from app.core.logging import configure_logging, get_logger
from app.core.settings import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.integrations.registry import build_integrations
from app.services.guards import RedisGuards
from app.services.ingest import IngestService
from app.services.queue import ArqJobQueue
from app.services.workflow import Workflow

log = get_logger(__name__)


def _problem(status: int, title: str, detail: str, request: Request) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail, "instance": request.url.path},
        status_code=status,
        media_type="application/problem+json",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Configure routes for these settings and open shared database and Redis pools during startup."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        sessionmaker = create_sessionmaker(engine)
        redis = await create_pool(RedisSettings.from_dsn(str(settings.redis_url)))
        guards, queue = RedisGuards(redis), ArqJobQueue(redis)
        app.state.container = Container(
            settings=settings,
            sessionmaker=sessionmaker,
            guards=guards,
            ingest=IngestService(sessionmaker, guards, queue),
            workflow=Workflow(sessionmaker, queue, guards, build_integrations(settings), settings),
        )
        log.info("api_started", env=settings.env, remediation_mode=settings.remediation_mode)
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="Agent Triage", version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        # Session capabilities and incident responses are specific to the authenticated client.
        if request.url.path.startswith(("/v1/incidents", "/v1/dashboard/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return _problem(exc.status_code, exc.title, str(exc), request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "Unprocessable Content", str(exc.errors()), request)

    app.include_router(health.router)
    app.include_router(alerts.router)
    app.include_router(incidents.router)
    if settings.dashboard_enabled:
        app.include_router(dashboard.router)
    return app
