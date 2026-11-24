import asyncio
import json
import time
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.api.auth import sign_body
from app.api.deps import Container
from app.domain.models import AlertSignal, AlertSource, Severity
from app.services.ingest import IngestOutcome
from tests.integration.conftest import HMAC_SECRET, INGEST_KEY, OPERATOR_KEY, FakeQueue

pytestmark = pytest.mark.integration

INGEST = {"Authorization": f"Bearer {INGEST_KEY}"}
OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}


def generic(message: str = "container OOMKilled exit code 137 on 10.0.0.1", **extra: Any) -> dict[str, Any]:
    return {"service": "checkout", "title": "Pod crash", "message": message, "severity": "high", **extra}


async def test_health_and_readiness(client: AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}
    metrics = await client.get("/metrics")
    assert "triage_signals_ingested_total" in metrics.text


async def test_ingest_creates_then_deduplicates(client: AsyncClient, queue: FakeQueue) -> None:
    first = await client.post("/v1/alerts/generic", json=generic(), headers=INGEST)
    assert first.status_code == 202
    [item] = first.json()["results"]
    assert item["outcome"] == "created"

    second = await client.post(
        "/v1/alerts/generic", json=generic("container OOMKilled exit code 137 on 10.0.0.9"), headers=INGEST
    )
    [dup] = second.json()["results"]
    assert dup == {"outcome": "attached", "incident_id": item["incident_id"], "occurrence_count": 2}
    assert queue.names() == ["triage_incident"]


async def test_concurrent_ingest_creates_single_incident(container: Container) -> None:
    signal = AlertSignal(source=AlertSource.GENERIC, service="checkout", title="race", message="boom", severity=Severity.HIGH)
    results = await asyncio.gather(*(container.ingest.ingest(signal, "test") for _ in range(10)))
    assert sum(r.outcome == IngestOutcome.CREATED for r in results) == 1
    assert len({r.incident_id for r in results}) == 1


async def test_authentication_and_scopes(client: AsyncClient) -> None:
    assert (await client.post("/v1/alerts/generic", json=generic())).status_code == 401
    assert (await client.post("/v1/alerts/generic", json=generic(), headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.post("/v1/alerts/generic", json=generic(), headers=OPERATOR)).status_code == 403
    assert (await client.get("/v1/incidents", headers=INGEST)).status_code == 403
    problem = await client.get("/v1/incidents")
    assert problem.status_code == 401
    assert problem.headers["content-type"] == "application/problem+json"


async def test_hmac_signed_alertmanager_webhook(client: AsyncClient) -> None:
    body = json.dumps(
        {
            "version": "4",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "KubePodOOM", "service": "cart"},
                    "annotations": {"summary": "OOMKilled"},
                },
                {"status": "resolved", "labels": {"alertname": "Gone", "service": "cart"}, "annotations": {}},
            ],
        }
    ).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Triage-Client": "alertmanager-hmac",
        "X-Triage-Timestamp": ts,
        "X-Triage-Signature": sign_body(HMAC_SECRET, ts, body),
    }
    resp = await client.post("/v1/alerts/alertmanager", content=body, headers=headers)
    assert resp.status_code == 202, resp.text
    assert [r["outcome"] for r in resp.json()["results"]] == ["created", "ignored"]

    headers["X-Triage-Signature"] = sign_body("wrong", ts, body)
    assert (await client.post("/v1/alerts/alertmanager", content=body, headers=headers)).status_code == 401


async def test_validation_size_and_idempotency(client: AsyncClient, container: Container) -> None:
    bad = await client.post("/v1/alerts/generic", json={"service": "x"}, headers=INGEST)
    assert bad.status_code == 422
    big = await client.post("/v1/alerts/generic", content=b"x" * (container.settings.max_body_bytes + 1), headers=INGEST)
    assert big.status_code == 413

    headers = {**INGEST, "Idempotency-Key": "delivery-1"}
    a = await client.post("/v1/alerts/generic", json=generic(), headers=headers)
    b = await client.post("/v1/alerts/generic", json=generic(), headers=headers)
    assert a.json() == b.json()
    incident = (await client.get(f"/v1/incidents/{a.json()['results'][0]['incident_id']}", headers=OPERATOR)).json()
    assert incident["occurrence_count"] == 1


async def test_incident_listing_and_pagination(client: AsyncClient) -> None:
    for i in range(5):
        await client.post("/v1/alerts/generic", json=generic(title=f"Alert {chr(65 + i)}"), headers=INGEST)
    page1 = (await client.get("/v1/incidents?limit=2", headers=OPERATOR)).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = (await client.get(f"/v1/incidents?limit=2&cursor={page1['next_cursor']}", headers=OPERATOR)).json()
    page3 = (await client.get(f"/v1/incidents?limit=2&cursor={page2['next_cursor']}", headers=OPERATOR)).json()
    ids = [i["id"] for p in (page1, page2, page3) for i in p["items"]]
    assert len(ids) == len(set(ids)) == 5
    assert page3["next_cursor"] is None
    assert (await client.get("/v1/incidents?status=RESOLVED", headers=OPERATOR)).json()["items"] == []
    assert (await client.get(f"/v1/incidents/{uuid.uuid4()}", headers=OPERATOR)).status_code == 404
