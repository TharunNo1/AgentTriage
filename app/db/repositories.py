import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AlertSignalRow, ApiClient, Approval, Incident, IncidentEvent, RemediationAction
from app.domain.models import OPEN_STATUSES, ApprovalStatus, IncidentStatus, SignalStatus


def encode_cursor(created_at: datetime, incident_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{incident_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    created, _, ident = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
    return datetime.fromisoformat(created), uuid.UUID(ident)


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, incident_id: uuid.UUID, *, for_update: bool = False) -> Incident | None:
        stmt = select(Incident).where(Incident.id == incident_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_open_by_fingerprint(self, fingerprint: str) -> Incident | None:
        """Lock the matching open incident so concurrent ingests can update its occurrence count."""
        stmt = select(Incident).where(Incident.fingerprint == fingerprint, Incident.status.in_(OPEN_STATUSES)).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def page(
        self, *, status: IncidentStatus | None, service: str | None, limit: int, cursor: str | None
    ) -> tuple[list[Incident], str | None]:
        """Page newest first, using the incident ID to break ties between identical creation times."""
        stmt = select(Incident)
        if status is not None:
            stmt = stmt.where(Incident.status == status)
        if service is not None:
            stmt = stmt.where(Incident.service == service)
        if cursor is not None:
            stmt = stmt.where(tuple_(Incident.created_at, Incident.id) < decode_cursor(cursor))
        stmt = stmt.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(limit + 1)
        rows = list((await self.session.execute(stmt)).scalars())
        next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
        return rows[:limit], next_cursor

    async def stuck_new(self, older_than: datetime) -> list[uuid.UUID]:
        stmt = select(Incident.id).where(Incident.status == IncidentStatus.NEW, Incident.created_at < older_than).limit(500)
        return list((await self.session.execute(stmt)).scalars())

    async def recent_signals(self, incident_id: uuid.UUID, limit: int = 20) -> list[AlertSignalRow]:
        stmt = (
            select(AlertSignalRow)
            .where(AlertSignalRow.incident_id == incident_id)
            .order_by(AlertSignalRow.received_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        incident: Incident,
        type_: str,
        actor: str,
        *,
        from_status: IncidentStatus | None = None,
        to_status: IncidentStatus | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            IncidentEvent(
                incident_id=incident.id,
                type=type_,
                actor=actor,
                from_status=from_status,
                to_status=to_status,
                data=data or {},
            )
        )

    async def has_type(self, incident_id: uuid.UUID, type_: str) -> bool:
        stmt = select(IncidentEvent.id).where(IncidentEvent.incident_id == incident_id, IncidentEvent.type == type_).limit(1)
        return (await self.session.scalar(stmt)) is not None

    async def firing_signals_after_action(self, incident_id: uuid.UUID, action_id: uuid.UUID) -> int | None:
        """Count later firing events, or return None if the action has no execution event."""
        # Ingest and execution append events under the same incident lock, which orders them across hosts.
        execution = select(IncidentEvent.id).where(
            IncidentEvent.incident_id == incident_id,
            IncidentEvent.type == "remediation_executed",
            IncidentEvent.data["action_id"].as_string() == str(action_id),
        )
        execution_id = await self.session.scalar(execution.order_by(IncidentEvent.id).limit(1))
        if execution_id is None:
            return None
        firing = select(func.count()).where(
            IncidentEvent.incident_id == incident_id,
            IncidentEvent.id > execution_id,
            IncidentEvent.type == "signal_attached",
            IncidentEvent.data["signal_status"].as_string() == SignalStatus.FIRING.value,
        )
        return (await self.session.execute(firing)).scalar_one()

    async def for_incident(self, incident_id: uuid.UUID, *, after_id: int, limit: int) -> list[IncidentEvent]:
        """Return events in timeline order, starting strictly after the last ID seen."""
        stmt = (
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id, IncidentEvent.id > after_id)
            .order_by(IncidentEvent.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())


class ActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, action_id: uuid.UUID, *, for_update: bool = False) -> RemediationAction | None:
        stmt = select(RemediationAction).where(RemediationAction.id == action_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, approval_id: uuid.UUID, *, for_update: bool = False) -> Approval | None:
        stmt = select(Approval).where(Approval.id == approval_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def pending_proposal(self, incident_id: uuid.UUID) -> tuple[Approval, RemediationAction] | None:
        stmt = (
            select(Approval, RemediationAction)
            .join(RemediationAction, RemediationAction.id == Approval.action_id)
            .where(Approval.incident_id == incident_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.expires_at.desc(), Approval.id)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def pending_for_incident(self, incident_id: uuid.UUID) -> list[Approval]:
        """Lock pending approvals for a decision or cancellation in the caller's transaction."""
        stmt = (
            select(Approval)
            .where(Approval.incident_id == incident_id, Approval.status == ApprovalStatus.PENDING)
            .with_for_update()
        )
        return list((await self.session.execute(stmt)).scalars())


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, run: AgentRun) -> None:
        self.session.add(run)


class ApiClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_by_key_hash(self, key_hash: str) -> ApiClient | None:
        stmt = select(ApiClient).where(ApiClient.key_hash == key_hash, ApiClient.active.is_(True))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> ApiClient | None:
        return (await self.session.execute(select(ApiClient).where(ApiClient.name == name))).scalar_one_or_none()

    async def all(self) -> list[ApiClient]:
        return list((await self.session.execute(select(ApiClient).order_by(ApiClient.name))).scalars())

    def add(self, client: ApiClient) -> None:
        self.session.add(client)
