import uuid
from datetime import timedelta
from typing import Any

from arq import Retry, cron
from arq.connections import RedisSettings

from app.agent.gemini import GeminiProvider
from app.agent.triage import StructuredTriageAgent
from app.core.logging import configure_logging, get_logger
from app.core.metrics import JOBS
from app.core.settings import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.integrations.registry import build_integrations
from app.services.guards import RedisGuards
from app.services.queue import ArqJobQueue
from app.services.workflow import Workflow

log = get_logger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level, settings.log_json)
    integrations = build_integrations(settings)
    if settings.triage_agent == "gemini":
        key, model = settings.gemini_api_key, settings.gemini_model
        if key is None or not key.get_secret_value().strip() or model is None or not model.strip():
            raise RuntimeError("Gemini triage requires TRIAGE_GEMINI_API_KEY and TRIAGE_GEMINI_MODEL")
        provider = GeminiProvider(api_key=key.get_secret_value(), model=model.strip())
        try:
            integrations = build_integrations(settings, agent=StructuredTriageAgent(provider))
        except Exception:
            await provider.aclose()
            raise
        ctx["gemini_provider"] = provider
    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["workflow"] = Workflow(
        create_sessionmaker(engine), ArqJobQueue(ctx["redis"]), RedisGuards(ctx["redis"]), integrations, settings
    )
    log.info("worker_started", remediation_mode=settings.remediation_mode)


async def shutdown(ctx: dict[str, Any]) -> None:
    provider: GeminiProvider | None = ctx.get("gemini_provider")
    try:
        if provider is not None:
            await provider.aclose()
    finally:
        await ctx["engine"].dispose()


def _wf(ctx: dict[str, Any]) -> Workflow:
    workflow: Workflow = ctx["workflow"]
    return workflow


def _backoff(ctx: dict[str, Any]) -> timedelta:
    return timedelta(seconds=min(5 * 2 ** (int(ctx["job_try"]) - 1), 300))


async def triage_incident(ctx: dict[str, Any], incident_id: str, operator_feedback: str | None = None) -> None:
    try:
        await _wf(ctx).triage(uuid.UUID(incident_id), operator_feedback)
        JOBS.labels(job="triage_incident", outcome="ok").inc()
    except Exception as exc:
        if int(ctx["job_try"]) >= settings.job_max_tries:
            JOBS.labels(job="triage_incident", outcome="exhausted").inc()
            await _wf(ctx).escalate_on_failure(uuid.UUID(incident_id), f"triage failed after retries: {exc!r}"[:500])
            return
        JOBS.labels(job="triage_incident", outcome="retry").inc()
        raise Retry(defer=_backoff(ctx)) from exc


async def execute_remediation(ctx: dict[str, Any], action_id: str) -> None:
    await _wf(ctx).execute_remediation(uuid.UUID(action_id))
    JOBS.labels(job="execute_remediation", outcome="ok").inc()


async def verify_remediation(ctx: dict[str, Any], action_id: str) -> None:
    await _wf(ctx).verify_remediation(uuid.UUID(action_id))
    JOBS.labels(job="verify_remediation", outcome="ok").inc()


async def expire_approval(ctx: dict[str, Any], approval_id: str) -> None:
    await _wf(ctx).expire_approval(uuid.UUID(approval_id))
    JOBS.labels(job="expire_approval", outcome="ok").inc()


async def sync_ticket(ctx: dict[str, Any], incident_id: str) -> None:
    try:
        await _wf(ctx).sync_ticket(uuid.UUID(incident_id))
    except Exception as exc:
        raise Retry(defer=_backoff(ctx)) from exc


async def send_notification(ctx: dict[str, Any], incident_id: str, kind: str) -> None:
    try:
        await _wf(ctx).send_notification(uuid.UUID(incident_id), kind)
    except Exception as exc:
        raise Retry(defer=_backoff(ctx)) from exc


async def requeue_stuck_incidents(ctx: dict[str, Any]) -> None:
    count = await _wf(ctx).requeue_stuck()
    if count:
        log.warning("requeued_stuck_incidents", count=count)


class WorkerSettings:
    functions = [triage_incident, execute_remediation, verify_remediation, expire_approval, sync_ticket, send_notification]  # noqa: RUF012
    cron_jobs = [cron(requeue_stuck_incidents, second={0}, run_at_startup=True)]  # noqa: RUF012
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    job_timeout = settings.job_timeout_seconds
    max_tries = settings.job_max_tries
    max_jobs = settings.worker_max_jobs
    keep_result = 3600
