from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.conftest import INGEST_KEY, OPERATOR_KEY, FakeQueue, Worker

pytestmark = pytest.mark.integration

INGEST = {"Authorization": f"Bearer {INGEST_KEY}"}
OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}
DB_POOL = "FATAL: too many connections for role app"


async def _open(client: AsyncClient, message: str, title: str = "Incident") -> str:
    resp = await client.post(
        "/v1/alerts/generic",
        json={"service": "checkout", "title": title, "message": message, "labels": {"namespace": "shop"}},
        headers=INGEST,
    )
    assert resp.status_code == 202, resp.text
    incident_id: str = resp.json()["results"][0]["incident_id"]
    return incident_id


async def _incident(client: AsyncClient, incident_id: str) -> dict[str, Any]:
    data: dict[str, Any] = (await client.get(f"/v1/incidents/{incident_id}", headers=OPERATOR)).json()
    return data


async def _statuses(client: AsyncClient, incident_id: str) -> list[str]:
    events = (await client.get(f"/v1/incidents/{incident_id}/events", headers=OPERATOR)).json()
    return [e["to_status"] for e in events if e["to_status"]]


async def test_tier1_auto_remediation_resolves(client: AsyncClient, worker: Worker) -> None:
    incident_id = await _open(client, "container OOMKilled exit code 137")
    await worker.drain()
    incident = await _incident(client, incident_id)
    assert incident["status"] == "RESOLVED"
    assert incident["tier"] == 1 and incident["error_class"] == "OOMKilled"
    assert incident["ticket_id"] and incident["resolved_at"]
    assert await _statuses(client, incident_id) == ["NEW", "TRIAGING", "REMEDIATING", "VERIFYING", "RESOLVED"]


async def test_failed_verification_escalates(client: AsyncClient, worker: Worker, queue: FakeQueue) -> None:
    incident_id = await _open(client, "container OOMKilled exit code 137")
    await worker.drain(skip=("expire_approval", "verify_remediation"))
    assert (await _incident(client, incident_id))["status"] == "VERIFYING"
    await _open(client, "container OOMKilled exit code 137")  # still firing after the action
    verify = next(j for j in queue.jobs if j.name == "verify_remediation")
    await worker.run(verify)
    assert (await _incident(client, incident_id))["status"] == "ESCALATED"


async def test_tier3_escalates_without_action(client: AsyncClient, worker: Worker, queue: FakeQueue) -> None:
    incident_id = await _open(client, "row checksum failed: data corrupted")
    await worker.drain()
    assert (await _incident(client, incident_id))["status"] == "ESCALATED"
    assert "execute_remediation" not in queue.names()


async def test_tier2_approval_then_resolves(client: AsyncClient, worker: Worker) -> None:
    incident_id = await _open(client, DB_POOL)
    await worker.drain()
    assert (await _incident(client, incident_id))["status"] == "AWAITING_APPROVAL"
    resp = await client.post(f"/v1/incidents/{incident_id}/approval", json={"decision": "approve"}, headers=OPERATOR)
    assert resp.status_code == 200, resp.text
    await worker.drain()
    assert (await _incident(client, incident_id))["status"] == "RESOLVED"
    again = await client.post(f"/v1/incidents/{incident_id}/approval", json={"decision": "approve"}, headers=OPERATOR)
    assert again.status_code == 409


async def test_reject_false_positive_suppresses_and_mutes(client: AsyncClient, worker: Worker) -> None:
    incident_id = await _open(client, DB_POOL)
    await worker.drain()
    missing_reason = await client.post(f"/v1/incidents/{incident_id}/approval", json={"decision": "reject"}, headers=OPERATOR)
    assert missing_reason.status_code in (400, 422)
    resp = await client.post(
        f"/v1/incidents/{incident_id}/approval", json={"decision": "reject", "reason": "false_positive"}, headers=OPERATOR
    )
    assert resp.json()["status"] == "SUPPRESSED"
    repeat = await client.post(
        "/v1/alerts/generic",
        json={"service": "checkout", "title": "Incident", "message": DB_POOL, "labels": {"namespace": "shop"}},
        headers=INGEST,
    )
    assert repeat.json()["results"][0]["outcome"] == "muted"


async def test_reject_handle_manually_assigns_operator(client: AsyncClient, worker: Worker) -> None:
    incident_id = await _open(client, DB_POOL)
    await worker.drain()
    resp = await client.post(
        f"/v1/incidents/{incident_id}/approval", json={"decision": "reject", "reason": "handle_manually"}, headers=OPERATOR
    )
    body = resp.json()
    assert (body["status"], body["assignee"]) == ("MANUAL", "alice")
    resolved = await client.post(f"/v1/incidents/{incident_id}/transition", json={"status": "RESOLVED"}, headers=OPERATOR)
    assert resolved.json()["status"] == "RESOLVED"
    reopen = await client.post(f"/v1/incidents/{incident_id}/transition", json={"status": "MANUAL"}, headers=OPERATOR)
    assert reopen.status_code == 409


async def test_reject_wrong_action_reproposes_once_then_manual(client: AsyncClient, worker: Worker) -> None:
    incident_id = await _open(client, DB_POOL)
    await worker.drain()
    reject = {"decision": "reject", "reason": "wrong_action", "note": "scale the pgbouncer pool instead"}
    path = f"/v1/incidents/{incident_id}/approval"
    original = (await client.get(path, headers=OPERATOR)).json()
    assert original["action_type"] and isinstance(original["params"], dict)
    first = await client.post(path, json={**reject, "approval_id": original["approval_id"]}, headers=OPERATOR)
    assert first.json()["status"] == "TRIAGING"
    await worker.drain()
    assert (await _incident(client, incident_id))["status"] == "AWAITING_APPROVAL"
    replacement = (await client.get(path, headers=OPERATOR)).json()
    assert replacement["approval_id"] != original["approval_id"]
    # An operator who still has the original proposal on screen must review its replacement before approving.
    stale = await client.post(path, json={"decision": "approve", "approval_id": original["approval_id"]}, headers=OPERATOR)
    assert stale.status_code == 409
    assert (await _incident(client, incident_id))["status"] == "AWAITING_APPROVAL"
    second = await client.post(path, json={**reject, "approval_id": replacement["approval_id"]}, headers=OPERATOR)
    assert second.json()["status"] == "MANUAL"


async def test_unanswered_approval_expires_to_escalated(client: AsyncClient, worker: Worker, queue: FakeQueue) -> None:
    incident_id = await _open(client, DB_POOL)
    await worker.drain()
    expire = next(j for j in queue.jobs if j.name == "expire_approval")
    assert expire.defer_by is not None
    await worker.run(expire)
    assert (await _incident(client, incident_id))["status"] == "ESCALATED"
    await worker.run(expire)  # idempotent
    assert (await _incident(client, incident_id))["status"] == "ESCALATED"


async def test_triage_job_is_idempotent(client: AsyncClient, worker: Worker, queue: FakeQueue) -> None:
    incident_id = await _open(client, "container OOMKilled exit code 137")
    await worker.drain()
    await worker.run(queue.jobs[0])
    assert await _statuses(client, incident_id) == ["NEW", "TRIAGING", "REMEDIATING", "VERIFYING", "RESOLVED"]
