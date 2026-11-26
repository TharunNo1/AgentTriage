import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.domain.models import IncidentSnapshot, IncidentStatus, Severity
from app.integrations.ticketing.jira import JiraSyncError, JiraTicketing

SITE = "https://triage-fixture.atlassian.net"


@pytest.fixture
def incident() -> IncidentSnapshot:
    return IncidentSnapshot(
        UUID(int=42), "checkout", "Alert", Severity.HIGH, IncidentStatus.ESCALATED, 1, datetime(2026, 1, 1, tzinfo=UTC)
    )


def jira(client: httpx.AsyncClient) -> JiraTicketing:
    return JiraTicketing(client, site=SITE, project="OPS", issue_type_id="10004", email="jira@example.com", token="fixture")


async def test_create_sends_deterministic_label_and_bounded_adf(incident: IncidentSnapshot) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == f"{SITE}/rest/api/3/issue"
        assert request.headers["authorization"].startswith("Basic ")
        fields = json.loads(request.content)["fields"]
        assert fields["labels"] == [f"agent-triage-{incident.id}"]
        assert fields["project"] == {"key": "OPS"}
        assert fields["issuetype"] == {"id": "10004"}
        description = fields["description"]
        assert description["type"] == "doc"
        assert description["content"][1]["content"][0]["text"] == "x" * 2000
        return httpx.Response(201, json={"key": "OPS-42"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        ticket = await jira(client).sync(incident, comment="x" * 3000)
    assert (ticket.ticket_id, ticket.url, ticket.created) == ("OPS-42", f"{SITE}/browse/OPS-42", True)


@pytest.mark.parametrize(
    ("issues", "is_last", "message"),
    [
        ([], True, "not visible"),
        ([{"key": "OPS-1"}, {"key": "OPS-2"}], True, "Multiple"),
        ([{"key": "OPS-1"}], False, "Multiple"),
    ],
)
async def test_recovery_search_never_creates(
    incident: IncidentSnapshot, issues: list[dict[str, str]], is_last: bool, message: str
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/search/jql"
        assert f'labels = "agent-triage-{incident.id}"' in json.loads(request.content)["jql"]
        return httpx.Response(200, json={"issues": issues, "isLast": is_last})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(JiraSyncError, match=message):
            await jira(client).sync(incident, comment="Analysis", allow_create=False)
