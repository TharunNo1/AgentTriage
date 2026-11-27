import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import hash_api_key
from app.api.main import create_app
from app.core.errors import ConflictError
from app.core.settings import Settings
from app.db.repositories import ApiClientRepository, ApprovalRepository, EventRepository, IncidentRepository

SETTINGS = Settings(
    database_url="postgresql+asyncpg://u:p@localhost/db",  # type: ignore[arg-type]
    remediation_mode="dry_run",
    dashboard_enabled=False,
)
INCIDENT = f"/v1/incidents/{uuid.UUID(int=1)}"
AUTH = {"Authorization": "Bearer test-key"}


async def test_dashboard_session_is_opt_in() -> None:
    app = create_app(SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/dashboard/session")).status_code == 404


@pytest.mark.parametrize(
    ("scopes", "read", "transition", "approval"),
    [
        (["ingest"], False, False, False),
        (["viewer"], True, False, False),
        (["responder"], True, True, False),
        (["approver"], True, False, True),
        (["operator"], True, True, True),
        (["responder", "approver"], True, True, True),
        (["unknown"], False, False, False),
    ],
)
async def test_dashboard_and_incident_permissions(
    monkeypatch: pytest.MonkeyPatch, scopes: list[str], read: bool, transition: bool, approval: bool
) -> None:
    settings = SETTINGS.model_copy(update={"dashboard_enabled": True})
    key_lookup = AsyncMock(return_value=SimpleNamespace(name="alice", scopes=scopes))
    monkeypatch.setattr(ApiClientRepository, "get_active_by_key_hash", key_lookup)
    monkeypatch.setattr(IncidentRepository, "page", AsyncMock(return_value=([], None)))
    monkeypatch.setattr(IncidentRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(EventRepository, "for_incident", AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalRepository, "pending_proposal", AsyncMock(return_value=None))
    # A 409 from the fake workflow shows authorization succeeded and the action reached the service.
    workflow = SimpleNamespace(
        decide_approval=AsyncMock(side_effect=ConflictError("Workflow reached")),
        operator_transition=AsyncMock(side_effect=ConflictError("Workflow reached")),
    )
    app = create_app(settings)
    app.state.container = SimpleNamespace(settings=settings, sessionmaker=MagicMock(), workflow=workflow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/dashboard")).status_code == 404
        assert (await client.get("/dashboard/assets/dashboard.js")).status_code == 404
        assert (await client.get("/v1/dashboard/session")).status_code == 401
        session = await client.get("/v1/dashboard/session", headers=AUTH)
        assert session.status_code == (200 if read else 403)
        assert session.headers["cache-control"] == "no-store"
        if read:
            assert session.json() == {
                "name": "alice",
                "can_transition": transition,
                "can_decide_approval": approval,
                "remediation_mode": "dry_run",
            }
        for path, allowed_status in [
            ("/v1/incidents", 200),
            (INCIDENT, 404),
            (f"{INCIDENT}/events", 200),
            (f"{INCIDENT}/approval", 200),
        ]:
            assert (await client.get(path, headers=AUTH)).status_code == (allowed_status if read else 403)

        decision = await client.post(
            f"{INCIDENT}/approval", headers=AUTH, json={"decision": "approve", "approval_id": str(uuid.UUID(int=2))}
        )
        change = await client.post(f"{INCIDENT}/transition", headers=AUTH, json={"status": "MANUAL"})
        assert decision.status_code == (409 if approval else 403)
        assert change.status_code == (409 if transition else 403)
        if approval:
            workflow.decide_approval.assert_awaited_once_with(
                uuid.UUID(int=1), approve=True, actor="alice", reason=None, note=None, approval_id=uuid.UUID(int=2)
            )
        else:
            workflow.decide_approval.assert_not_awaited()
        if transition:
            workflow.operator_transition.assert_awaited_once()
        else:
            workflow.operator_transition.assert_not_awaited()
        key_lookup.assert_awaited_with(hash_api_key("test-key"))
        key_lookup.return_value = None
        assert (await client.get("/v1/incidents", headers=AUTH)).status_code == 401
