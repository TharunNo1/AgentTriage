import pytest
from pydantic import ValidationError

from app.api.normalizers import (
    AlertmanagerPayload,
    GcpMonitoringPayload,
    GenericAlert,
    from_alertmanager,
    from_gcp_monitoring,
    from_generic,
    parse_severity,
)
from app.domain.models import AlertSource, Severity, SignalStatus

ALERTMANAGER = {
    "version": "4",
    "status": "firing",
    "receiver": "triage",
    "groupKey": '{}:{alertname="KubePodOOM"}',
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "KubePodOOM", "service": "checkout", "severity": "critical", "namespace": "shop"},
            "annotations": {"description": "Container OOMKilled", "summary": "OOM"},
            "startsAt": "2026-11-24T10:00:00Z",
            "fingerprint": "abc123",
        },
        {
            "status": "resolved",
            "labels": {"alertname": "HighLatency", "job": "payments"},
            "annotations": {},
        },
    ],
}

GCP = {
    "version": "1.2",
    "incident": {
        "incident_id": "0.abc",
        "state": "open",
        "summary": "CPU utilization above 90%",
        "policy_name": "High CPU",
        "resource": {"type": "k8s_container", "labels": {"container_name": "api", "namespace_name": "prod"}},
        "severity": "Warning",
        "policy_user_labels": {"team": "core"},
    },
}


def test_alertmanager_normalization() -> None:
    signals = from_alertmanager(AlertmanagerPayload.model_validate(ALERTMANAGER))
    assert len(signals) == 2
    first, second = signals
    assert (first.source, first.service, first.title) == (AlertSource.ALERTMANAGER, "checkout", "KubePodOOM")
    assert first.message == "Container OOMKilled"
    assert first.severity == Severity.CRITICAL
    assert first.external_id == "abc123"
    assert first.labels["namespace"] == "shop"
    assert (second.service, second.status, second.message) == ("payments", SignalStatus.RESOLVED, "HighLatency")


def test_alertmanager_rejects_empty_and_oversized_batches() -> None:
    with pytest.raises(ValidationError):
        AlertmanagerPayload.model_validate({**ALERTMANAGER, "alerts": []})
    with pytest.raises(ValidationError):
        AlertmanagerPayload.model_validate({**ALERTMANAGER, "alerts": ALERTMANAGER["alerts"][:1] * 501})  # type: ignore[index]


def test_gcp_normalization() -> None:
    [signal] = from_gcp_monitoring(GcpMonitoringPayload.model_validate(GCP))
    assert (signal.source, signal.service, signal.title) == (AlertSource.GCP_MONITORING, "api", "High CPU")
    assert signal.severity == Severity.MEDIUM
    assert signal.status == SignalStatus.FIRING
    assert signal.labels["team"] == "core"
    closed = {**GCP, "incident": {**GCP["incident"], "state": "closed"}}  # type: ignore[dict-item]
    assert from_gcp_monitoring(GcpMonitoringPayload.model_validate(closed))[0].status == SignalStatus.RESOLVED


def test_generic_normalization_and_limits() -> None:
    [signal] = from_generic(GenericAlert(service="checkout", title="Boom", message="OOMKilled", severity="p1", trace_id="t-1"))
    assert (signal.source, signal.severity, signal.trace_id) == (AlertSource.GENERIC, Severity.HIGH, "t-1")
    with pytest.raises(ValidationError):
        GenericAlert(service="", title="t", message="m")
    with pytest.raises(ValidationError):
        GenericAlert(service="s", title="t", message="m" * 20_001)


@pytest.mark.parametrize(("raw", "expected"), [("P0", Severity.CRITICAL), (" warning ", Severity.MEDIUM), (None, Severity.HIGH)])
def test_parse_severity(raw: str | None, expected: Severity) -> None:
    assert parse_severity(raw) == expected
