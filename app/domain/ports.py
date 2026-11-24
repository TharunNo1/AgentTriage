from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.domain.models import IncidentSnapshot, ProposedAction, Severity, TriageResult


@dataclass(frozen=True, slots=True)
class TriageContext:
    incident_id: UUID
    service: str
    title: str
    messages: list[str]
    trace_ids: list[str]
    labels: dict[str, str] = field(default_factory=dict)
    operator_feedback: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunStats:
    agent: str
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TicketRef:
    ticket_id: str
    url: str
    created: bool


@dataclass(frozen=True, slots=True)
class Notification:
    kind: str
    subject: str
    body: str
    severity: Severity
    incident: IncidentSnapshot


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    succeeded: bool
    detail: str


class TriageAgent(Protocol):
    name: str

    async def triage(self, ctx: TriageContext) -> tuple[TriageResult, AgentRunStats]: ...


class Ticketing(Protocol):
    async def sync(self, incident: IncidentSnapshot, comment: str) -> TicketRef: ...


class Notifier(Protocol):
    async def notify(self, notification: Notification) -> None: ...


class RemediationExecutor(Protocol):
    async def execute(self, action: ProposedAction, *, dry_run: bool) -> ActionOutcome: ...
