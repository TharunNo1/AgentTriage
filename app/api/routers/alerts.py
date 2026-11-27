from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, ValidationError

from app.api.auth import authenticate, require_scope
from app.api.deps import ContainerDep
from app.api.normalizers import (
    AlertmanagerPayload,
    GcpMonitoringPayload,
    GenericAlert,
    from_alertmanager,
    from_gcp_monitoring,
    from_generic,
)
from app.api.schemas import IngestItem, IngestResponse
from app.core.errors import DomainError, PayloadTooLargeError, RateLimitedError
from app.domain.models import AlertSignal

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])

Hdr = Annotated[str | None, Header()]


class RequestValidationProblem(DomainError):
    status_code = 422
    title = "Unprocessable Content"


async def _ingest[P: BaseModel](
    request: Request,
    container: ContainerDep,
    model: type[P],
    normalize: Callable[[P], list[AlertSignal]],
    authorization: str | None,
    x_triage_client: str | None,
    x_triage_timestamp: str | None,
    x_triage_signature: str | None,
    idempotency_key: str | None,
) -> IngestResponse:
    settings = container.settings
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > settings.max_body_bytes:
        raise PayloadTooLargeError(f"Body exceeds {settings.max_body_bytes} bytes")
    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise PayloadTooLargeError(f"Body exceeds {settings.max_body_bytes} bytes")

    principal = await authenticate(
        authorization=authorization,
        hmac_client=x_triage_client,
        hmac_timestamp=x_triage_timestamp,
        hmac_signature=x_triage_signature,
        body=body,
        settings=settings,
        sessionmaker=container.sessionmaker,
    )
    require_scope(principal, "ingest")
    if not await container.guards.allow_request(principal.name, settings.rate_limit_per_minute):
        raise RateLimitedError("Rate limit exceeded")

    # Replays use the original client's response and still count toward that client's request limit.
    if idempotency_key:
        cached = await container.guards.get_idempotent(principal.name, idempotency_key)
        if cached is not None:
            return IngestResponse.model_validate(cached)

    try:
        payload = model.model_validate_json(body)
    except ValidationError as exc:
        raise RequestValidationProblem(str(exc.errors(include_url=False, include_context=False))) from exc
    signals = normalize(payload)

    results = []
    for signal in signals:
        result = await container.ingest.ingest(signal, principal.name)
        results.append(
            IngestItem(outcome=result.outcome, incident_id=result.incident_id, occurrence_count=result.occurrence_count)
        )
    response = IngestResponse(results=results)
    if idempotency_key:
        await container.guards.store_idempotent(
            principal.name, idempotency_key, response.model_dump(mode="json"), settings.idempotency_ttl_seconds
        )
    return response


@router.post("/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def alertmanager(
    request: Request,
    container: ContainerDep,
    authorization: Hdr = None,
    x_triage_client: Hdr = None,
    x_triage_timestamp: Hdr = None,
    x_triage_signature: Hdr = None,
    idempotency_key: Hdr = None,
) -> IngestResponse:
    """Ingest a grouped webhook and return one outcome per alert in payload order."""
    return await _ingest(
        request,
        container,
        AlertmanagerPayload,
        from_alertmanager,
        authorization,
        x_triage_client,
        x_triage_timestamp,
        x_triage_signature,
        idempotency_key,
    )


@router.post("/gcp-monitoring", status_code=status.HTTP_202_ACCEPTED)
async def gcp_monitoring(
    request: Request,
    container: ContainerDep,
    authorization: Hdr = None,
    x_triage_client: Hdr = None,
    x_triage_timestamp: Hdr = None,
    x_triage_signature: Hdr = None,
    idempotency_key: Hdr = None,
) -> IngestResponse:
    """Ingest a Cloud Monitoring incident notification, including recovery updates."""
    return await _ingest(
        request,
        container,
        GcpMonitoringPayload,
        from_gcp_monitoring,
        authorization,
        x_triage_client,
        x_triage_timestamp,
        x_triage_signature,
        idempotency_key,
    )


@router.post("/generic", status_code=status.HTTP_202_ACCEPTED)
async def generic(
    request: Request,
    container: ContainerDep,
    authorization: Hdr = None,
    x_triage_client: Hdr = None,
    x_triage_timestamp: Hdr = None,
    x_triage_signature: Hdr = None,
    idempotency_key: Hdr = None,
) -> IngestResponse:
    """Ingest one signal using the generic webhook format."""
    return await _ingest(
        request,
        container,
        GenericAlert,
        from_generic,
        authorization,
        x_triage_client,
        x_triage_timestamp,
        x_triage_signature,
        idempotency_key,
    )
