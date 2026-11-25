import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.models import (
    OPEN_STATUSES,
    ActionStatus,
    ActionType,
    AlertSource,
    ApprovalStatus,
    IncidentStatus,
    RejectionReason,
    Severity,
    SignalStatus,
)

JsonDict = JSON().with_variant(JSONB(), "postgresql")


def _enum[E: enum.Enum](enum_cls: type[E], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e], validate_strings=True)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


_OPEN_STATUS_SQL = ", ".join(f"'{s.value}'" for s in sorted(OPEN_STATUSES))


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(_enum(IncidentStatus, "incident_status"), nullable=False)
    tier: Mapped[int | None] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(String(255))
    rca_summary: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reproposal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ticket_id: Mapped[str | None] = mapped_column(String(64))
    ticket_url: Mapped[str | None] = mapped_column(String(500))
    assignee: Mapped[str | None] = mapped_column(String(255))
    last_signal_at: Mapped[datetime] = _now()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    signals: Mapped[list["AlertSignalRow"]] = relationship(back_populates="incident", order_by="AlertSignalRow.received_at")

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        Index(
            "uq_incidents_open_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text(f"status IN ({_OPEN_STATUS_SQL})"),
            sqlite_where=text(f"status IN ({_OPEN_STATUS_SQL})"),
        ),
        Index("ix_incidents_status_created", "status", "created_at"),
        Index("ix_incidents_created_id", "created_at", "id"),
    )


class AlertSignalRow(Base):
    __tablename__ = "alert_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    source: Mapped[AlertSource] = mapped_column(_enum(AlertSource, "alert_source"), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SignalStatus] = mapped_column(_enum(SignalStatus, "signal_status"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(255))
    labels: Mapped[dict[str, Any]] = mapped_column(JsonDict, nullable=False, default=dict)
    raw: Mapped[dict[str, Any]] = mapped_column(JsonDict, nullable=False, default=dict)
    received_at: Mapped[datetime] = _now()

    incident: Mapped[Incident] = relationship(back_populates="signals")


class IncidentEvent(Base):
    """Append-only timeline and audit log."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[IncidentStatus | None] = mapped_column(_enum(IncidentStatus, "incident_status"))
    to_status: Mapped[IncidentStatus | None] = mapped_column(_enum(IncidentStatus, "incident_status"))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JsonDict, nullable=False, default=dict)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_incident_events_incident_id_id", "incident_id", "id"),)


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    action_type: Mapped[ActionType] = mapped_column(_enum(ActionType, "action_type"), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JsonDict, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ActionStatus] = mapped_column(_enum(ActionStatus, "action_status"), nullable=False)
    dry_run: Mapped[bool | None] = mapped_column(Boolean)
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("remediation_actions.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(_enum(ApprovalStatus, "approval_status"), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    rejection_reason: Mapped[RejectionReason | None] = mapped_column(_enum(RejectionReason, "rejection_reason"))
    note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True, nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class ApiClient(Base):
    __tablename__ = "api_clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JsonDict, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
