import asyncio
from email.errors import HeaderParseError
from email.headerregistry import Address
from hashlib import sha256

import httpx
from pydantic import BaseModel, ValidationError

from app.domain.ports import Notification
from app.integrations.notify import NotificationDeliveryError, event_label


class EmailDeliveryError(NotificationDeliveryError):
    pass


class _SendResponse(BaseModel):
    id: str | None = None
    name: str | None = None


def _mailbox(value: str, setting: str) -> str:
    try:
        address = Address(addr_spec=value)
    except (ValueError, HeaderParseError):
        raise ValueError(f"{setting} must contain one email address") from None
    if not address.username or not address.domain:
        raise ValueError(f"{setting} must contain one email address")
    return address.addr_spec


class ResendNotifier:
    def __init__(self, client: httpx.AsyncClient, *, api_key: str, sender: str, recipient: str) -> None:
        self._client = client
        self._api_key = api_key
        self._sender = _mailbox(sender, "TRIAGE_RESEND_FROM_EMAIL")
        self._recipient = _mailbox(recipient, "TRIAGE_RESEND_TO_EMAIL")

    async def notify(self, notification: Notification) -> None:
        if not notification.delivery_id:
            raise EmailDeliveryError("Email delivery requires a notification job ID", retryable=False)

        key = sha256(notification.delivery_id.encode()).hexdigest()
        label = event_label(notification.kind)
        # The same queued event must generate the same payload even if the incident later changes severity.
        payload = {
            "from": self._sender,
            "to": [self._recipient],
            "subject": f"Agent Triage | {label}",
            "text": f"{label}\nIncident {notification.incident.id}",
        }
        try:
            async with asyncio.timeout(10):
                response = await self._client.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}", "Idempotency-Key": key},
                    follow_redirects=False,
                )
        except (httpx.RequestError, TimeoutError):
            raise EmailDeliveryError("Email request failed", retryable=True) from None

        status = response.status_code
        if response.is_success or status == 409:
            try:
                result = _SendResponse.model_validate_json(response.content)
            except ValidationError:
                raise EmailDeliveryError("Invalid email provider response", retryable=response.is_success) from None
            if response.is_success and result.id:
                return
            if status == 409 and result.name == "concurrent_idempotent_requests":
                raise EmailDeliveryError("Email delivery is already in progress", retryable=True)
        raise EmailDeliveryError(
            f"Email delivery failed (HTTP {status})", retryable=response.is_success or status == 429 or status >= 500
        )
