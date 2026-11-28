import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.metrics import SIGNALS_INGESTED
from app.db.models import AlertSignalRow, Incident
from app.db.repositories import EventRepository, IncidentRepository
from app.db.session import transaction
from app.domain.fingerprint import fingerprint
from app.domain.models import AlertSignal, IncidentStatus, SignalStatus
from app.services.guards import RedisGuards
from app.services.queue import JobQueue

log = get_logger(__name__)


class IngestOutcome(StrEnum):
    CREATED = "created"
    ATTACHED = "attached"
    MUTED = "muted"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: IngestOutcome
    fingerprint: str
    incident_id: uuid.UUID | None = None
    occurrence_count: int = 0


def triage_job_id(incident_id: uuid.UUID, attempt: int = 0) -> str:
    """Reuse the queue key for retries and allocate a distinct key for each operator-requested reproposal."""
    return f"triage:{incident_id}:{attempt}"


class IngestService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], guards: RedisGuards, queue: JobQueue) -> None:
        self._sessionmaker = sessionmaker
        self._guards = guards
        self._queue = queue

    async def ingest(self, signal: AlertSignal, client_name: str) -> IngestResult:
        """Deduplicate against open incidents and enqueue initial triage after a new incident commits."""
        fp = fingerprint(signal.service, signal.title, signal.message)
        if await self._guards.is_muted(fp):
            result = IngestResult(IngestOutcome.MUTED, fp)
        else:
            try:
                result = await self._persist(signal, client_name, fp)
            except IntegrityError:
                # A concurrent request created the open incident for this fingerprint first; attach to it instead.
                result = await self._persist(signal, client_name, fp)
            if result.outcome == IngestOutcome.CREATED and result.incident_id is not None:
                await self._queue.enqueue("triage_incident", str(result.incident_id), job_id=triage_job_id(result.incident_id))
        SIGNALS_INGESTED.labels(source=signal.source.value, outcome=result.outcome.value).inc()
        log.info("signal_ingested", outcome=result.outcome, incident_id=str(result.incident_id), service=signal.service)
        return result

    async def _persist(self, signal: AlertSignal, client_name: str, fp: str) -> IngestResult:
        async with transaction(self._sessionmaker) as session:
            incidents, events = IncidentRepository(session), EventRepository(session)
            incident = await incidents.get_open_by_fingerprint(fp)
            if incident is None:
                # A recovery with no open incident has nothing to attach to.
                if signal.status == SignalStatus.RESOLVED:
                    return IngestResult(IngestOutcome.IGNORED, fp)
                incident = Incident(
                    id=uuid.uuid4(),
                    fingerprint=fp,
                    service=signal.service,
                    title=signal.title,
                    severity=signal.severity,
                    status=IncidentStatus.NEW,
                    occurrence_count=1,
                )
                session.add(incident)
                await session.flush()
                events.add(incident, "incident_created", client_name, to_status=IncidentStatus.NEW, data={"fingerprint": fp})
                outcome = IngestOutcome.CREATED
            else:
                if signal.status == SignalStatus.FIRING:
                    incident.occurrence_count += 1
                    incident.last_signal_at = datetime.now(UTC)
                events.add(incident, "signal_attached", client_name, data={"signal_status": signal.status.value})
                outcome = IngestOutcome.ATTACHED
            session.add(_signal_row(signal, incident.id, client_name))
            return IngestResult(outcome, fp, incident.id, incident.occurrence_count)


def _signal_row(signal: AlertSignal, incident_id: uuid.UUID, client_name: str) -> AlertSignalRow:
    return AlertSignalRow(
        incident_id=incident_id,
        source=signal.source,
        client_name=client_name,
        status=signal.status,
        external_id=signal.external_id,
        service=signal.service,
        title=signal.title,
        message=signal.message,
        severity=signal.severity,
        trace_id=signal.trace_id,
        labels=signal.labels,
        raw=signal.raw,
    )
