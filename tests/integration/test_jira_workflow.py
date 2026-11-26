import asyncio
from uuid import UUID

import httpx
import pytest

from app.api.deps import Container
from app.integrations.registry import build_integrations
from app.integrations.ticketing.jira import JiraSyncError, JiraTicketing
from app.services.workflow import Workflow
from tests.integration.conftest import FakeQueue
from tests.integration.test_workflow import _incident, _open

pytestmark = pytest.mark.integration


async def test_jira_recovers_after_lost_create_response(
    client: httpx.AsyncClient, container: Container, queue: FakeQueue
) -> None:
    incident_id = await _open(client, "Checksum mismatch")
    calls: list[tuple[str, str]] = []
    create_started = asyncio.Event()
    release_create = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        calls.append((method, path))
        if path == "/rest/api/3/issue":
            create_started.set()
            await release_create.wait()
            raise httpx.ReadTimeout("lost response")
        if path == "/rest/api/3/search/jql":
            issues = [{"key": "OPS-42"}] if release_create.is_set() else []
            return httpx.Response(200, json={"issues": issues, "isLast": True})
        assert (method, path) == ("PUT", "/rest/api/3/issue/OPS-42")
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        settings = container.settings.model_copy(update={"ticketing": "jira"})
        adapter = JiraTicketing(
            transport,
            site="https://triage-fixture.atlassian.net",
            project="OPS",
            issue_type_id="10004",
            email="jira@example.com",
            token="fixture",
        )
        workflow = Workflow(
            container.sessionmaker, queue, container.guards, build_integrations(settings, ticketing=adapter), settings
        )
        async with asyncio.TaskGroup() as tasks:

            async def first_attempt() -> None:
                with pytest.raises(JiraSyncError, match="request failed"):
                    await workflow.sync_ticket(UUID(incident_id))

            tasks.create_task(first_attempt())
            try:
                async with asyncio.timeout(3):
                    await create_started.wait()
                with pytest.raises(JiraSyncError, match="not visible"):
                    await workflow.sync_ticket(UUID(incident_id))
            finally:
                release_create.set()
        await workflow.sync_ticket(UUID(incident_id))
        await workflow.sync_ticket(UUID(incident_id))

    incident = await _incident(client, incident_id)
    assert incident["ticket_id"] == "OPS-42"
    assert incident["ticket_url"] == "https://triage-fixture.atlassian.net/browse/OPS-42"
    assert calls == [
        ("POST", "/rest/api/3/issue"),
        ("POST", "/rest/api/3/search/jql"),
        ("POST", "/rest/api/3/search/jql"),
        ("PUT", "/rest/api/3/issue/OPS-42"),
        ("PUT", "/rest/api/3/issue/OPS-42"),
    ]
