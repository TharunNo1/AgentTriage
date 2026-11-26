import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from arq import Retry, cron
from arq.connections import RedisSettings

from app.agent.gemini import GeminiProvider
from app.agent.triage import StructuredTriageAgent
from app.core.logging import configure_logging, get_logger
from app.core.metrics import JOBS
from app.core.settings import get_settings
from app.db.session import create_engine, create_sessionmaker
from app.domain.ports import Notifier
from app.integrations.notify import NotificationDeliveryError
from app.integrations.notify.resend import EmailDeliveryError, ResendNotifier
from app.integrations.notify.slack import SlackDeliveryError, SlackNotifier
from app.integrations.registry import build_integrations
from app.integrations.ticketing.jira import JiraSyncError, JiraTicketing
from app.services.guards import RedisGuards
from app.services.queue import ArqJobQueue
from app.services.workflow import Workflow

log = get_logger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level, settings.log_json)
    async with AsyncExitStack() as resources:
        agent = None
        if settings.triage_agent == "gemini":
            key, model = settings.gemini_api_key, settings.gemini_model
            if key is None or not key.get_secret_value().strip() or model is None or not model.strip():
                raise RuntimeError("Gemini triage requires TRIAGE_GEMINI_API_KEY and TRIAGE_GEMINI_MODEL")
            provider = GeminiProvider(api_key=key.get_secret_value(), model=model.strip())
            resources.push_async_callback(provider.aclose)
            agent = StructuredTriageAgent(provider)

        notifier: Notifier | None = None
        if settings.notifier == "slack":
            webhook = settings.slack_webhook_url
            if webhook is None:
                raise RuntimeError("Slack notifications require TRIAGE_SLACK_WEBHOOK_URL")
            client = await resources.enter_async_context(httpx.AsyncClient())
            notifier = SlackNotifier(client, webhook.get_secret_value())
        elif settings.notifier == "resend":
            email_key = settings.resend_api_key
            sender, recipient = settings.resend_from_email, settings.resend_to_email
            if email_key is None or not email_key.get_secret_value().strip() or not sender or not recipient:
                raise RuntimeError(
                    "Email notifications require TRIAGE_RESEND_API_KEY, TRIAGE_RESEND_FROM_EMAIL and TRIAGE_RESEND_TO_EMAIL"
                )
            client = await resources.enter_async_context(httpx.AsyncClient())
            notifier = ResendNotifier(client, api_key=email_key.get_secret_value().strip(), sender=sender, recipient=recipient)

        ticketing = None
        if settings.ticketing == "jira":
            site, project = settings.jira_site, settings.jira_project
            email, issue_type, token = settings.jira_email, settings.jira_issue_type_id, settings.jira_api_token
            if not site or not project or not email or not issue_type or token is None or not token.get_secret_value().strip():
                raise RuntimeError("Jira ticketing requires all TRIAGE_JIRA_* settings")
            jira_client = await resources.enter_async_context(httpx.AsyncClient())
            ticketing = JiraTicketing(
                jira_client, site=site, project=project, issue_type_id=issue_type, email=email, token=token.get_secret_value()
            )

        integrations = build_integrations(settings, agent=agent, notifier=notifier, ticketing=ticketing)
        engine = create_engine(settings)
        resources.push_async_callback(engine.dispose)
        ctx["engine"] = engine
        ctx["workflow"] = Workflow(
            create_sessionmaker(engine), ArqJobQueue(ctx["redis"]), RedisGuards(ctx["redis"]), integrations, settings
        )
        ctx["resources"] = resources.pop_all()
    log.info("worker_started", remediation_mode=settings.remediation_mode, notifier=settings.notifier)


async def shutdown(ctx: dict[str, Any]) -> None:
    resources: AsyncExitStack = ctx["resources"]
    await resources.aclose()


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
    except JiraSyncError as exc:
        retry = int(ctx["job_try"]) < settings.job_max_tries
        JOBS.labels(job="sync_ticket", outcome="retry" if retry else "failed").inc()
        log.warning("jira_ticket_sync_failed", incident_id=incident_id, retry=retry, error=str(exc))
        if retry:
            raise Retry(defer=_backoff(ctx)) from exc
        raise
    except Exception as exc:
        raise Retry(defer=_backoff(ctx)) from exc
    JOBS.labels(job="sync_ticket", outcome="ok").inc()


async def send_notification(ctx: dict[str, Any], incident_id: str, kind: str) -> None:
    try:
        if settings.notifier == "resend" and datetime.now(UTC) - ctx["enqueue_time"] >= timedelta(hours=23):
            raise EmailDeliveryError("Email notification is outside the retry window", retryable=False)
        await _wf(ctx).send_notification(uuid.UUID(incident_id), kind, delivery_id=ctx.get("job_id"))
    except NotificationDeliveryError as exc:
        exhausted = int(ctx["job_try"]) >= settings.job_max_tries
        retry = exc.retryable and not exhausted
        JOBS.labels(job="send_notification", outcome="retry" if retry else "failed").inc()
        event = "slack_notification_failed" if isinstance(exc, SlackDeliveryError) else "email_notification_failed"
        log.warning(event, incident_id=incident_id, kind=kind, retry=retry, error=str(exc))
        if retry:
            raise Retry(defer=_backoff(ctx)) from exc
        raise
    except Exception as exc:
        raise Retry(defer=_backoff(ctx)) from exc
    JOBS.labels(job="send_notification", outcome="ok").inc()


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
