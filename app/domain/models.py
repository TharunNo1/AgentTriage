from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal
from uuid import UUID

RemediationMode = Literal["disabled", "dry_run", "enabled"]


class IncidentStatus(StrEnum):
    NEW = "NEW"
    TRIAGING = "TRIAGING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    MANUAL = "MANUAL"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


TERMINAL_STATUSES = frozenset({IncidentStatus.RESOLVED, IncidentStatus.SUPPRESSED})
OPEN_STATUSES = frozenset(set(IncidentStatus) - TERMINAL_STATUSES)


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Tier(IntEnum):
    AUTO_REMEDIATE = 1
    APPROVAL_REQUIRED = 2
    ESCALATE = 3


class SignalStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertSource(StrEnum):
    ALERTMANAGER = "alertmanager"
    GCP_MONITORING = "gcp_monitoring"
    GENERIC = "generic"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RejectionReason(StrEnum):
    FALSE_POSITIVE = "false_positive"
    HANDLE_MANUALLY = "handle_manually"
    WRONG_ACTION = "wrong_action"


class ActionType(StrEnum):
    RESTART_DEPLOYMENT = "restart_deployment"
    SCALE_DEPLOYMENT = "scale_deployment"
    DELETE_POD = "delete_pod"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    SUCCEEDED = "succeeded"
    DRY_RUN = "dry_run"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AlertSignal:
    """A single alert normalized from any source."""

    source: AlertSource
    service: str
    title: str
    message: str
    severity: Severity
    status: SignalStatus = SignalStatus.FIRING
    trace_id: str | None = None
    external_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    type: ActionType
    params: dict[str, Any]
    rationale: str


@dataclass(frozen=True, slots=True)
class TriageResult:
    tier: Tier
    severity: Severity
    error_class: str
    rca_summary: str
    evidence: list[str] = field(default_factory=list)
    proposed_action: ProposedAction | None = None


@dataclass(frozen=True, slots=True)
class IncidentSnapshot:
    """Read-only view of an incident handed to integration ports."""

    id: UUID
    service: str
    title: str
    severity: Severity
    status: IncidentStatus
    occurrence_count: int
    created_at: datetime
    tier: Tier | None = None
    rca_summary: str | None = None
    ticket_id: str | None = None
    ticket_url: str | None = None
