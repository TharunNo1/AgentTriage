import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.domain.models import IncidentSnapshot, IncidentStatus, Severity
from app.domain.ports import Notification
from app.integrations.notify.slack import SlackDeliveryError, SlackNotifier

WEBHOOK = "https://hooks.slack.com/services/test/channel/fixture"


@pytest.fixture
def notification() -> Notification:
    incident = IncidentSnapshot(
        UUID(int=42),
        "private service",
        "<!channel>",
        Severity.HIGH,
        IncidentStatus.AWAITING_APPROVAL,
        1,
        datetime(2026, 11, 26, tzinfo=UTC),
    )
    return Notification("approval_requested", "<!channel>", "private alert body", Severity.HIGH, incident)


async def test_sends_only_notification_metadata(notification: Notification) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == WEBHOOK
        payload = json.loads(request.content)
        assert str(notification.incident.id) in payload["text"]
        assert "approval requested" in payload["text"].lower()
        assert "high" in payload["text"].lower()
        assert "private" not in payload["text"]
        assert "<!channel>" not in payload["text"]
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await SlackNotifier(client, WEBHOOK).notify(notification)


@pytest.mark.parametrize(("status", "retryable"), [(302, False), (403, False), (429, True), (503, True), (200, False)])
async def test_rejects_unsuccessful_responses(notification: Notification, status: int, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=WEBHOOK))
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(SlackDeliveryError) as failure:
            await SlackNotifier(client, WEBHOOK).notify(notification)
    assert failure.value.retryable is retryable
    assert WEBHOOK not in str(failure.value)


async def test_transport_error_hides_secret(notification: Notification) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SlackDeliveryError) as failure:
            await SlackNotifier(client, WEBHOOK).notify(notification)
    assert failure.value.retryable
    assert WEBHOOK not in str(failure.value)


@pytest.mark.parametrize(
    "url", ["http://hooks.slack.com/services/a/b/c", "https://evil.example/services/a/b/c", WEBHOOK + "?secret=x"]
)
def test_rejects_invalid_webhook(url: str) -> None:
    with pytest.raises(ValueError, match="TRIAGE_SLACK_WEBHOOK_URL"):
        SlackNotifier(httpx.AsyncClient(), url)
