import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request

from app.api.auth import Principal, authenticate, require_scope
from app.api.deps import Container, ContainerDep
from app.api.schemas import ApprovalDecision, EventOut, IncidentOut, IncidentPage, OperatorTransition
from app.core.errors import NotFoundError
from app.db.repositories import EventRepository, IncidentRepository
from app.domain.models import IncidentStatus

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])


async def _operator(request: Request, container: Container, authorization: str | None) -> Principal:
    principal = await authenticate(
        authorization=authorization,
        hmac_client=None,
        hmac_timestamp=None,
        hmac_signature=None,
        body=b"",
        settings=container.settings,
        sessionmaker=container.sessionmaker,
    )
    require_scope(principal, "operator")
    return principal


@router.get("")
async def list_incidents(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    status: IncidentStatus | None = None,
    service: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> IncidentPage:
    await _operator(request, container, authorization)
    async with container.sessionmaker() as session:
        rows, next_cursor = await IncidentRepository(session).page(status=status, service=service, limit=limit, cursor=cursor)
    return IncidentPage(items=[IncidentOut.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.get("/{incident_id}")
async def get_incident(
    incident_id: uuid.UUID, request: Request, container: ContainerDep, authorization: Annotated[str | None, Header()] = None
) -> IncidentOut:
    await _operator(request, container, authorization)
    async with container.sessionmaker() as session:
        incident = await IncidentRepository(session).get(incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} not found")
    return IncidentOut.model_validate(incident)


@router.get("/{incident_id}/events")
async def list_events(
    incident_id: uuid.UUID,
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[EventOut]:
    await _operator(request, container, authorization)
    async with container.sessionmaker() as session:
        events = await EventRepository(session).for_incident(incident_id, after_id=after_id, limit=limit)
    return [EventOut.model_validate(e) for e in events]


@router.post("/{incident_id}/approval")
async def decide_approval(
    incident_id: uuid.UUID,
    body: ApprovalDecision,
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> IncidentOut:
    principal = await _operator(request, container, authorization)
    incident = await container.workflow.decide_approval(
        incident_id, approve=body.decision == "approve", actor=principal.name, reason=body.reason, note=body.note
    )
    return IncidentOut.model_validate(incident)


@router.post("/{incident_id}/transition")
async def operator_transition(
    incident_id: uuid.UUID,
    body: OperatorTransition,
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> IncidentOut:
    principal = await _operator(request, container, authorization)
    incident = await container.workflow.operator_transition(incident_id, body.status, actor=principal.name, note=body.note)
    return IncidentOut.model_validate(incident)
