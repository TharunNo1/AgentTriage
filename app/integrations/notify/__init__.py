from typing import Final

_EVENT_LABELS: Final = {
    "approval_requested": "Approval requested",
    "escalated": "Escalated",
    "resolved": "Resolved",
    "manual": "Assigned for manual handling",
    "suppressed": "Suppressed",
}


class NotificationDeliveryError(RuntimeError):
    """Report a delivery failure and whether another worker attempt could succeed."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def event_label(kind: str) -> str:
    return _EVENT_LABELS.get(kind, "Incident updated")
