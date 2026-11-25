import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import IncidentStatus, RejectionReason, Severity
from app.services.ingest import IngestOutcome


class IngestItem(BaseModel):
    outcome: IngestOutcome
    incident_id: uuid.UUID | None
    occurrence_count: int


class IngestResponse(BaseModel):
    results: list[IngestItem]


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service: str
    title: str
    severity: Severity
    status: IncidentStatus
    tier: int | None
    error_class: str | None
    rca_summary: str | None
    occurrence_count: int
    ticket_id: str | None
    ticket_url: str | None
    assignee: str | None
    created_at: datetime
    updated_at: datetime
    last_signal_at: datetime
    resolved_at: datetime | None


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    next_cursor: str | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    from_status: IncidentStatus | None
    to_status: IncidentStatus | None
    actor: str
    data: dict[str, Any]
    created_at: datetime


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: RejectionReason | None = None
    note: str | None = Field(default=None, max_length=2000)


class OperatorTransition(BaseModel):
    status: Literal[IncidentStatus.RESOLVED, IncidentStatus.SUPPRESSED, IncidentStatus.MANUAL]
    note: str | None = Field(default=None, max_length=2000)
