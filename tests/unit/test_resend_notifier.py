import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app.domain.models import IncidentSnapshot, IncidentStatus, Severity
from app.domain.ports import Notification
from app.integrations.notify.resend import EmailDeliveryError, ResendNotifier

API_KEY = "fixture-api-key"


@pytest.fixture
def notification() -> Notification:
    incident = IncidentSnapshot(
        UUID(int=42),
        "private service",
        "private title",
        Severity.HIGH,
        IncidentStatus.ESCALATED,
        1,
        datetime(2026, 11, 26, tzinfo=UTC),
    )
    return Notification("escalated", incident.title, "private analysis", Severity.HIGH, incident, delivery_id="first-job")


def _notifier(client: httpx.AsyncClient) -> ResendNotifier:
    return ResendNotifier(client, api_key=API_KEY, sender="alerts@example.com", recipient="oncall@example.com")


async def test_retries_reuse_key_and_payload_after_ambiguous_response(notification: Notification) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout(API_KEY)
        return httpx.Response(200, json={"id": "email-42"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        notifier = _notifier(client)
        with pytest.raises(EmailDeliveryError) as failure:
            await notifier.notify(notification)
        assert failure.value.retryable
        assert API_KEY not in str(failure.value)
        await notifier.notify(replace(notification, severity=Severity.CRITICAL))
        await notifier.notify(replace(notification, delivery_id="second-job"))

    first, retry, next_event = requests
    assert first.method == "POST"
    assert str(first.url) == "https://api.resend.com/emails"
    assert first.headers["Authorization"] == f"Bearer {API_KEY}"
    assert first.headers["Idempotency-Key"] == retry.headers["Idempotency-Key"]
    assert first.headers["Idempotency-Key"] != next_event.headers["Idempotency-Key"]
    assert first.content == retry.content
    assert json.loads(first.content) == {
        "from": "alerts@example.com",
        "to": ["oncall@example.com"],
        "subject": "Agent Triage | Escalated",
        "text": f"Escalated\nIncident {notification.incident.id}",
    }


@pytest.mark.parametrize(
    ("status", "name", "retryable"),
    [
        (200, "invalid_response", True),
        (401, "invalid_api_key", False),
        (409, "concurrent_idempotent_requests", True),
        (409, "invalid_idempotent_request", False),
        (429, "rate_limit_exceeded", True),
        (503, "application_error", True),
    ],
)
async def test_provider_failures_are_sanitized(notification: Notification, status: int, name: str, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"name": name, "message": API_KEY}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(EmailDeliveryError) as failure:
            await _notifier(client).notify(notification)
    assert failure.value.retryable is retryable
    assert API_KEY not in str(failure.value)


async def test_requires_job_identity_and_one_recipient(notification: Notification) -> None:
    transport = httpx.MockTransport(lambda request: pytest.fail("Unexpected HTTP request"))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(EmailDeliveryError, match="job ID") as failure:
            await _notifier(client).notify(replace(notification, delivery_id=None))
        assert not failure.value.retryable
        with pytest.raises(ValueError, match="TRIAGE_RESEND_TO_EMAIL"):
            ResendNotifier(client, api_key=API_KEY, sender="alerts@example.com", recipient="a@example.com, b@example.com")


async def test_worker_does_not_replay_jobs_outside_provider_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    from app.workers import main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"notifier": "resend"}))
    workflow = AsyncMock()
    ctx = {
        "workflow": workflow,
        "job_id": "queued-job",
        "job_try": 1,
        "enqueue_time": datetime.now(UTC) - timedelta(days=1),
    }
    incident_id = UUID(int=42)
    with pytest.raises(EmailDeliveryError, match="retry window"):
        await main.send_notification(ctx, str(incident_id), "escalated")
    workflow.send_notification.assert_not_awaited()

    ctx["enqueue_time"] = datetime.now(UTC)
    await main.send_notification(ctx, str(incident_id), "escalated")
    workflow.send_notification.assert_awaited_once_with(incident_id, "escalated", delivery_id="queued-job")
