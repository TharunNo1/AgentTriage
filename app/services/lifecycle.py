from datetime import UTC, datetime
from typing import Any

from app.core.metrics import INCIDENT_TRANSITIONS
from app.db.models import Incident
from app.db.repositories import EventRepository
from app.domain.models import TERMINAL_STATUSES, IncidentSnapshot, IncidentStatus, Severity, Tier
from app.domain.state_machine import ensure_transition


def transition(
    events: EventRepository,
    incident: Incident,
    target: IncidentStatus,
    actor: str,
    *,
    by_operator: bool = False,
    data: dict[str, Any] | None = None,
) -> None:
    """The only place incident status changes. Writes the audit event in the caller's transaction."""
    current = incident.status
    ensure_transition(current, target, by_operator=by_operator)
    incident.status = target
    if target in TERMINAL_STATUSES:
        incident.resolved_at = datetime.now(UTC)
    events.add(incident, "status_changed", actor, from_status=current, to_status=target, data=data)
    INCIDENT_TRANSITIONS.labels(to_status=target.value).inc()


def snapshot(incident: Incident) -> IncidentSnapshot:
    """Copy the fields adapters need so they can work without an ORM session."""
    return IncidentSnapshot(
        id=incident.id,
        service=incident.service,
        title=incident.title,
        severity=Severity(incident.severity),
        status=IncidentStatus(incident.status),
        occurrence_count=incident.occurrence_count,
        created_at=incident.created_at,
        tier=Tier(incident.tier) if incident.tier is not None else None,
        rca_summary=incident.rca_summary,
        ticket_id=incident.ticket_id,
        ticket_url=incident.ticket_url,
    )
