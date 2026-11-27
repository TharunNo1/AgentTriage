import asyncio
import re

import httpx

from app.domain.ports import Notification
from app.integrations.notify import NotificationDeliveryError, event_label

_WEBHOOK = re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+")


class SlackDeliveryError(NotificationDeliveryError):
    pass


class SlackNotifier:
    def __init__(self, client: httpx.AsyncClient, webhook: str) -> None:
        if _WEBHOOK.fullmatch(webhook) is None:
            raise ValueError("TRIAGE_SLACK_WEBHOOK_URL must be a Slack incoming webhook URL")
        self._client = client
        self._webhook = webhook

    async def notify(self, notification: Notification) -> None:
        """Send event metadata only, keeping alert text and analysis out of Slack."""
        label = event_label(notification.kind)
        incident = notification.incident
        message = f"Agent Triage | {label}\nIncident {incident.id}\nSeverity {notification.severity.value}"
        try:
            async with asyncio.timeout(10):
                response = await self._client.post(self._webhook, json={"text": message}, follow_redirects=False)
        except (httpx.RequestError, TimeoutError):
            # HTTPX exceptions can include the credential-bearing URL.
            raise SlackDeliveryError("Slack webhook request failed", retryable=True) from None

        if response.status_code != 200 or response.text.strip() != "ok":
            status = response.status_code
            raise SlackDeliveryError(
                f"Slack webhook delivery failed (HTTP {status})",
                retryable=status == 429 or status >= 500,
            )
