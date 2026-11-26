import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.logging import get_logger
from app.core.metrics import AGENT_LATENCY
from app.core.settings import Settings
from app.db.models import AgentRun, Approval, Incident, RemediationAction
from app.db.repositories import ActionRepository, AgentRunRepository, ApprovalRepository, EventRepository, IncidentRepository
from app.db.session import transaction
from app.domain.models import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    IncidentStatus,
    ProposedAction,
    RejectionReason,
    Severity,
    TriageResult,
)
from app.domain.ports import Notification, TriageContext
from app.domain.state_machine import can_transition, next_status_after_rejection, next_status_after_triage
from app.integrations.registry import Integrations
from app.services.guards import RedisGuards
from app.services.ingest import triage_job_id
from app.services.lifecycle import snapshot, transition
from app.services.queue import JobQueue

log = get_logger(__name__)

SYSTEM_ACTOR = "system"
NotificationKind = Literal["approval_requested", "escalated", "resolved", "manual", "suppressed"]

_SUBJECTS: dict[str, str] = {
    "approval_requested": "[APPROVAL NEEDED] {service}: {title}",
    "escalated": "[ESCALATED] {service}: {title}",
    "resolved": "[RESOLVED] {service}: {title}",
    "manual": "[MANUAL] {service}: {title}",
    "suppressed": "[SUPPRESSED] {service}: {title}",
}


class Workflow:
    """Drives incidents through the lifecycle (ADR 0006). Called by worker jobs and operator API endpoints.

    External calls (agent, ticketing, executor, notifier) happen outside DB transactions; every step re-reads and
    re-checks state under a row lock, so jobs are idempotent and safe to retry.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        queue: JobQueue,
        guards: RedisGuards,
        integrations: Integrations,
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._queue = queue
        self._guards = guards
        self._integrations = integrations
        self._settings = settings

    async def triage(self, incident_id: uuid.UUID, operator_feedback: str | None = None) -> None:
        async with transaction(self._sessionmaker) as session:
            incident = await IncidentRepository(session).get(incident_id, for_update=True)
            if incident is None or incident.status not in (IncidentStatus.NEW, IncidentStatus.TRIAGING):
                return
            if incident.status == IncidentStatus.NEW:
                transition(EventRepository(session), incident, IncidentStatus.TRIAGING, SYSTEM_ACTOR)
            signals = await IncidentRepository(session).recent_signals(incident_id)
            labels: dict[str, str] = {}
            for signal in reversed(signals):
                labels.update({str(k): str(v) for k, v in signal.labels.items()})
            ctx = TriageContext(
                incident_id=incident.id,
                service=incident.service,
                title=incident.title,
                messages=[s.message for s in signals],
                trace_ids=sorted({s.trace_id for s in signals if s.trace_id}),
                labels=labels,
                operator_feedback=operator_feedback,
            )

        agent = self._integrations.agent
        started = time.perf_counter()
        try:
            result, stats = await agent.triage(ctx)
        except Exception as exc:
            await self._record_agent_failure(incident_id, agent.name, started, exc)
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        AGENT_LATENCY.labels(agent=agent.name).observe(latency_ms / 1000)

        async with transaction(self._sessionmaker) as session:
            incident = await IncidentRepository(session).get(incident_id, for_update=True)
            if incident is None or incident.status != IncidentStatus.TRIAGING:
                return
            self._apply_triage_result(incident, result)
            AgentRunRepository(session).add(
                AgentRun(
                    incident_id=incident_id,
                    agent=stats.agent,
                    model=stats.model,
                    prompt_version=stats.prompt_version,
                    input_tokens=stats.input_tokens,
                    output_tokens=stats.output_tokens,
                    latency_ms=latency_ms,
                    outcome="ok",
                )
            )
            events = EventRepository(session)
            events.add(incident, "triaged", stats.agent, data=_triage_event_data(result))

            target = next_status_after_triage(result, remediation_mode=self._settings.remediation_mode)
            transition(events, incident, target, SYSTEM_ACTOR, data={"tier": int(result.tier)})
            action = self._add_action(session, incident, result.proposed_action) if result.proposed_action else None
            approval = None
            if target == IncidentStatus.AWAITING_APPROVAL and action is not None:
                await session.flush()  # approvals.action_id references the action row
                approval = Approval(
                    id=uuid.uuid4(),
                    incident_id=incident.id,
                    action_id=action.id,
                    status=ApprovalStatus.PENDING,
                    expires_at=datetime.now(UTC) + timedelta(seconds=self._settings.approval_ttl_seconds),
                )
                session.add(approval)
                events.add(incident, "approval_requested", SYSTEM_ACTOR, data={"approval_id": str(approval.id)})

        await self._queue.enqueue("sync_ticket", str(incident_id), job_id=f"ticket:{incident_id}:{uuid.uuid4()}")
        if target == IncidentStatus.REMEDIATING and action is not None:
            await self._queue.enqueue("execute_remediation", str(action.id), job_id=f"execute:{action.id}")
        elif approval is not None:
            await self._queue.enqueue(
                "expire_approval",
                str(approval.id),
                job_id=f"expire:{approval.id}",
                defer_by=timedelta(seconds=self._settings.approval_ttl_seconds),
            )
            await self._notify(incident_id, "approval_requested")
        elif target == IncidentStatus.ESCALATED:
            await self._notify(incident_id, "escalated")

    async def execute_remediation(self, action_id: uuid.UUID) -> None:
        async with transaction(self._sessionmaker) as session:
            action = await ActionRepository(session).get(action_id, for_update=True)
            if action is None or action.status != ActionStatus.PROPOSED:
                return
            incident = await IncidentRepository(session).get(action.incident_id)
            if incident is None or incident.status != IncidentStatus.REMEDIATING:
                return
            proposed = ProposedAction(type=ActionType(action.action_type), params=dict(action.params), rationale=action.rationale)

        dry_run = self._settings.remediation_mode != "enabled"
        outcome = await self._integrations.executor.execute(proposed, dry_run=dry_run)

        async with transaction(self._sessionmaker) as session:
            action = await ActionRepository(session).get(action_id, for_update=True)
            incident = await IncidentRepository(session).get(action.incident_id, for_update=True) if action else None
            if action is None or incident is None or action.status != ActionStatus.PROPOSED:
                return
            action.dry_run = dry_run
            action.result = outcome.detail
            action.executed_at = datetime.now(UTC)
            action.status = (
                (ActionStatus.DRY_RUN if dry_run else ActionStatus.SUCCEEDED) if outcome.succeeded else ActionStatus.FAILED
            )
            events = EventRepository(session)
            events.add(
                incident, "remediation_executed", SYSTEM_ACTOR, data={"action_id": str(action.id), "status": action.status.value}
            )
            target = IncidentStatus.VERIFYING if outcome.succeeded else IncidentStatus.ESCALATED
            transition(events, incident, target, SYSTEM_ACTOR, data={"detail": outcome.detail})

        if outcome.succeeded:
            await self._queue.enqueue(
                "verify_remediation",
                str(action.id),
                job_id=f"verify:{action.id}",
                defer_by=timedelta(seconds=self._settings.verify_delay_seconds),
            )
        else:
            await self._notify(incident.id, "escalated")

    async def verify_remediation(self, action_id: uuid.UUID) -> None:
        """Phase 1 verification: the incident is healthy if no new firing signals arrived after the action ran."""
        async with transaction(self._sessionmaker) as session:
            action = await ActionRepository(session).get(action_id)
            if action is None or action.executed_at is None:
                return
            incidents = IncidentRepository(session)
            incident = await incidents.get(action.incident_id, for_update=True)
            if incident is None or incident.status != IncidentStatus.VERIFYING:
                return
            new_signals = await incidents.firing_signals_since(incident.id, action.executed_at)
            target = IncidentStatus.RESOLVED if new_signals == 0 else IncidentStatus.ESCALATED
            transition(
                EventRepository(session), incident, target, SYSTEM_ACTOR, data={"firing_signals_after_action": new_signals}
            )
        await self._notify(incident.id, "resolved" if target == IncidentStatus.RESOLVED else "escalated")

    async def expire_approval(self, approval_id: uuid.UUID) -> None:
        async with transaction(self._sessionmaker) as session:
            approval = await ApprovalRepository(session).get(approval_id, for_update=True)
            if approval is None or approval.status != ApprovalStatus.PENDING:
                return
            incident = await IncidentRepository(session).get(approval.incident_id, for_update=True)
            approval.status = ApprovalStatus.EXPIRED
            approval.decided_at = datetime.now(UTC)
            if incident is None or incident.status != IncidentStatus.AWAITING_APPROVAL:
                return
            await self._cancel_action(session, approval.action_id)
            transition(
                EventRepository(session), incident, IncidentStatus.ESCALATED, SYSTEM_ACTOR, data={"reason": "approval_expired"}
            )
        await self._notify(incident.id, "escalated")

    async def decide_approval(
        self,
        incident_id: uuid.UUID,
        *,
        approve: bool,
        actor: str,
        reason: RejectionReason | None = None,
        note: str | None = None,
    ) -> Incident:
        if not approve and reason is None:
            raise DomainError("A rejection reason is required")
        notify_kind: NotificationKind | None = None
        retriage_attempt: int | None = None
        target: IncidentStatus = IncidentStatus.REMEDIATING
        async with transaction(self._sessionmaker) as session:
            incident = await self._get_for_update(session, incident_id)
            if incident.status != IncidentStatus.AWAITING_APPROVAL:
                raise ConflictError(f"Incident is {incident.status}, not awaiting approval")
            pending = await ApprovalRepository(session).pending_for_incident(incident_id)
            if not pending:
                raise ConflictError("Incident has no pending approval")
            approval = pending[0]
            approval.decided_by, approval.note, approval.decided_at = actor, note, datetime.now(UTC)
            events = EventRepository(session)
            if approve:
                approval.status = ApprovalStatus.APPROVED
                events.add(incident, "approval_decided", actor, data={"decision": "approved", "note": note})
                transition(events, incident, target, actor)
            else:
                assert reason is not None
                approval.status, approval.rejection_reason = ApprovalStatus.REJECTED, reason
                await self._cancel_action(session, approval.action_id)
                events.add(
                    incident, "approval_decided", actor, data={"decision": "rejected", "reason": reason.value, "note": note}
                )
                target = next_status_after_rejection(
                    reason, reproposals=incident.reproposal_count, max_reproposals=self._settings.max_reproposals
                )
                transition(events, incident, target, actor, data={"reason": reason.value})
                notify_kind, retriage_attempt = self._after_manual_status(incident, target, actor)
            action_id = approval.action_id

        if approve:
            await self._queue.enqueue("execute_remediation", str(action_id), job_id=f"execute:{action_id}")
        elif retriage_attempt is not None:
            await self._queue.enqueue(
                "triage_incident", str(incident_id), note, job_id=triage_job_id(incident_id, retriage_attempt)
            )
        if notify_kind is not None:
            await self._notify(incident_id, notify_kind)
        if target == IncidentStatus.SUPPRESSED:
            await self._guards.mute(incident.fingerprint, self._settings.mute_window_seconds)
        return incident

    async def operator_transition(
        self, incident_id: uuid.UUID, target: IncidentStatus, *, actor: str, note: str | None
    ) -> Incident:
        async with transaction(self._sessionmaker) as session:
            incident = await self._get_for_update(session, incident_id)
            if not can_transition(incident.status, target, by_operator=True):
                raise ConflictError(f"Cannot move incident from {incident.status} to {target}")
            for approval in await ApprovalRepository(session).pending_for_incident(incident_id):
                approval.status, approval.decided_by, approval.decided_at = ApprovalStatus.REJECTED, actor, datetime.now(UTC)
                approval.note = "superseded by operator transition"
                await self._cancel_action(session, approval.action_id)
            transition(EventRepository(session), incident, target, actor, by_operator=True, data={"note": note})
            notify_kind, _ = self._after_manual_status(incident, target, actor)
        if target == IncidentStatus.SUPPRESSED:
            await self._guards.mute(incident.fingerprint, self._settings.mute_window_seconds)
        if notify_kind is not None:
            await self._notify(incident_id, notify_kind)
        return incident

    async def escalate_on_failure(self, incident_id: uuid.UUID, reason: str) -> None:
        async with transaction(self._sessionmaker) as session:
            incident = await IncidentRepository(session).get(incident_id, for_update=True)
            if incident is None or not can_transition(incident.status, IncidentStatus.ESCALATED):
                return
            transition(EventRepository(session), incident, IncidentStatus.ESCALATED, SYSTEM_ACTOR, data={"reason": reason})
        await self._notify(incident_id, "escalated")

    async def requeue_stuck(self) -> int:
        older_than = datetime.now(UTC) - timedelta(seconds=self._settings.stuck_incident_seconds)
        async with self._sessionmaker() as session:
            ids = await IncidentRepository(session).stuck_new(older_than)
        for incident_id in ids:
            await self._queue.enqueue("triage_incident", str(incident_id), job_id=triage_job_id(incident_id))
        return len(ids)

    async def sync_ticket(self, incident_id: uuid.UUID) -> None:
        jira_enabled = self._settings.ticketing == "jira"
        allow_create = True
        async with transaction(self._sessionmaker) as session:
            incident = await IncidentRepository(session).get(incident_id, for_update=jira_enabled)
            if incident is None:
                return
            snap = snapshot(incident)
            if jira_enabled:
                if snap.ticket_url and snap.ticket_url.startswith("https://tickets.invalid/"):
                    snap = replace(snap, ticket_id=None, ticket_url=None)
                if snap.ticket_id is None:
                    events = EventRepository(session)
                    # Commit the reservation before Jira I/O so a crashed attempt can only be reconciled.
                    allow_create = not await events.has_type(incident_id, "jira_create_reserved")
                    if allow_create:
                        events.add(incident, "jira_create_reserved", SYSTEM_ACTOR)
        ticket = await self._integrations.ticketing.sync(snap, comment=snap.rca_summary or snap.title, allow_create=allow_create)
        async with transaction(self._sessionmaker) as session:
            incident = await self._get_for_update(session, incident_id)
            if not jira_enabled and incident.ticket_id != snap.ticket_id:
                return
            incident.ticket_id, incident.ticket_url = ticket.ticket_id, ticket.url
            EventRepository(session).add(
                incident, "ticket_synced", SYSTEM_ACTOR, data={"ticket_id": ticket.ticket_id, "created": ticket.created}
            )

    async def send_notification(self, incident_id: uuid.UUID, kind: str, *, delivery_id: str | None = None) -> None:
        async with transaction(self._sessionmaker) as session:
            incident = await IncidentRepository(session).get(incident_id)
            if incident is None:
                return
            snap = snapshot(incident)
            await self._integrations.notifier.notify(
                Notification(
                    kind=kind,
                    subject=_SUBJECTS.get(kind, "[{kind}] {service}: {title}").format(
                        kind=kind.upper(), service=incident.service, title=incident.title
                    ),
                    body=incident.rca_summary or incident.title,
                    severity=Severity(incident.severity),
                    incident=snap,
                    delivery_id=delivery_id,
                )
            )
            EventRepository(session).add(incident, "notification_sent", SYSTEM_ACTOR, data={"kind": kind})

    # helpers

    async def _notify(self, incident_id: uuid.UUID, kind: NotificationKind) -> None:
        await self._queue.enqueue(
            "send_notification", str(incident_id), kind, job_id=f"notify:{incident_id}:{kind}:{uuid.uuid4()}"
        )

    async def _get_for_update(self, session: AsyncSession, incident_id: uuid.UUID) -> Incident:
        incident = await IncidentRepository(session).get(incident_id, for_update=True)
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        return incident

    @staticmethod
    def _apply_triage_result(incident: Incident, result: TriageResult) -> None:
        incident.tier = int(result.tier)
        incident.severity = result.severity
        incident.error_class = result.error_class
        incident.rca_summary = result.rca_summary

    @staticmethod
    def _add_action(session: AsyncSession, incident: Incident, proposed: ProposedAction) -> RemediationAction:
        action = RemediationAction(
            id=uuid.uuid4(),
            incident_id=incident.id,
            action_type=proposed.type,
            params=proposed.params,
            rationale=proposed.rationale,
            status=ActionStatus.PROPOSED,
        )
        session.add(action)
        return action

    @staticmethod
    async def _cancel_action(session: AsyncSession, action_id: uuid.UUID) -> None:
        action = await ActionRepository(session).get(action_id, for_update=True)
        if action is not None and action.status == ActionStatus.PROPOSED:
            action.status = ActionStatus.CANCELLED

    @staticmethod
    def _after_manual_status(
        incident: Incident, target: IncidentStatus, actor: str
    ) -> tuple[NotificationKind | None, int | None]:
        if target == IncidentStatus.MANUAL:
            incident.assignee = actor
            return "manual", None
        if target == IncidentStatus.TRIAGING:
            incident.reproposal_count += 1
            return None, incident.reproposal_count
        if target == IncidentStatus.SUPPRESSED:
            return "suppressed", None
        if target == IncidentStatus.RESOLVED:
            return "resolved", None
        return None, None

    async def _record_agent_failure(self, incident_id: uuid.UUID, agent: str, started: float, exc: Exception) -> None:
        async with transaction(self._sessionmaker) as session:
            AgentRunRepository(session).add(
                AgentRun(
                    incident_id=incident_id,
                    agent=agent,
                    model="unknown",
                    prompt_version="unknown",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    outcome="error",
                    error=repr(exc)[:2000],
                )
            )
        log.warning("agent_failed", incident_id=str(incident_id), error=repr(exc))


def _triage_event_data(result: TriageResult) -> dict[str, object]:
    return {
        "tier": int(result.tier),
        "severity": result.severity.value,
        "error_class": result.error_class,
        "rca_summary": result.rca_summary,
        "proposed_action": (
            {"type": result.proposed_action.type.value, "params": result.proposed_action.params}
            if result.proposed_action
            else None
        ),
    }
