import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.api.auth import Principal, authenticate, require_permission
from app.api.deps import ContainerDep
from app.api.schemas import ApprovalDecision, EventOut, IncidentOut, IncidentPage, OperatorTransition, PendingProposal
from app.core.errors import NotFoundError
from app.db.repositories import ApprovalRepository, EventRepository, IncidentRepository
from app.domain.models import IncidentStatus

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])


async def incident_principal(container: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> Principal:
    return await authenticate(
        authorization=authorization,
        hmac_client=None,
        hmac_timestamp=None,
        hmac_signature=None,
        body=b"",
        settings=container.settings,
        sessionmaker=container.sessionmaker,
    )


IncidentPrincipal = Annotated[Principal, Depends(incident_principal)]


@router.get("")
async def list_incidents(
    container: ContainerDep,
    principal: IncidentPrincipal,
    status: IncidentStatus | None = None,
    service: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> IncidentPage:
    """Return matching incidents newest first. Use next_cursor with the same filters to continue."""
    require_permission(principal, "read")
    async with container.sessionmaker() as session:
        rows, next_cursor = await IncidentRepository(session).page(status=status, service=service, limit=limit, cursor=cursor)
    return IncidentPage(items=[IncidentOut.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.get("/{incident_id}")
async def get_incident(incident_id: uuid.UUID, container: ContainerDep, principal: IncidentPrincipal) -> IncidentOut:
    require_permission(principal, "read")
    async with container.sessionmaker() as session:
        incident = await IncidentRepository(session).get(incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} not found")
    return IncidentOut.model_validate(incident)


@router.get("/{incident_id}/events")
async def list_events(
    incident_id: uuid.UUID,
    container: ContainerDep,
    principal: IncidentPrincipal,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[EventOut]:
    """Return events whose ID exceeds after_id, ordered from oldest to newest."""
    require_permission(principal, "read")
    async with container.sessionmaker() as session:
        events = await EventRepository(session).for_incident(incident_id, after_id=after_id, limit=limit)
    return [EventOut.model_validate(e) for e in events]


@router.get("/{incident_id}/approval")
async def get_pending_proposal(
    incident_id: uuid.UUID, container: ContainerDep, principal: IncidentPrincipal
) -> PendingProposal | None:
    """Return the pending action for review, or null when no unexpired proposal is available."""
    require_permission(principal, "read")
    async with container.sessionmaker() as session:
        proposal = await ApprovalRepository(session).pending_proposal(incident_id)
    if proposal is None:
        return None
    approval, action = proposal
    if approval.expires_at <= datetime.now(UTC):
        return None
    return PendingProposal(
        approval_id=approval.id, expires_at=approval.expires_at, action_type=action.action_type, params=action.params
    )


@router.post("/{incident_id}/approval")
async def decide_approval(
    incident_id: uuid.UUID,
    body: ApprovalDecision,
    container: ContainerDep,
    principal: IncidentPrincipal,
) -> IncidentOut:
    require_permission(principal, "approval")
    incident = await container.workflow.decide_approval(
        incident_id,
        approve=body.decision == "approve",
        actor=principal.name,
        reason=body.reason,
        note=body.note,
        approval_id=body.approval_id,
    )
    return IncidentOut.model_validate(incident)


@router.post("/{incident_id}/transition")
async def operator_transition(
    incident_id: uuid.UUID,
    body: OperatorTransition,
    container: ContainerDep,
    principal: IncidentPrincipal,
) -> IncidentOut:
    require_permission(principal, "transition")
    incident = await container.workflow.operator_transition(incident_id, body.status, actor=principal.name, note=body.note)
    return IncidentOut.model_validate(incident)
