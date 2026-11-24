"""Convert source-specific webhook payloads into AlertSignals."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import AlertSignal, AlertSource, Severity, SignalStatus

_SEVERITY_ALIASES: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "p0": Severity.CRITICAL,
    "page": Severity.CRITICAL,
    "emergency": Severity.CRITICAL,
    "high": Severity.HIGH,
    "p1": Severity.HIGH,
    "error": Severity.HIGH,
    "major": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "p2": Severity.MEDIUM,
    "warning": Severity.MEDIUM,
    "warn": Severity.MEDIUM,
    "low": Severity.LOW,
    "p3": Severity.LOW,
    "minor": Severity.LOW,
    "info": Severity.INFO,
    "informational": Severity.INFO,
    "none": Severity.INFO,
}


def parse_severity(value: str | None, default: Severity = Severity.HIGH) -> Severity:
    return _SEVERITY_ALIASES.get((value or "").strip().lower(), default)


def _first(mapping: dict[str, str], *keys: str) -> str | None:
    return next((mapping[k] for k in keys if mapping.get(k)), None)


# Alertmanager (webhook_config, payload version 4)


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    fingerprint: str | None = None
    generatorURL: str | None = None


class AlertmanagerPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str | None = None
    status: str
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=500)


def from_alertmanager(payload: AlertmanagerPayload) -> list[AlertSignal]:
    signals = []
    for alert in payload.alerts:
        labels = alert.labels
        title = labels.get("alertname", "UnnamedAlert")
        signals.append(
            AlertSignal(
                source=AlertSource.ALERTMANAGER,
                service=_first(labels, "service", "app", "app_kubernetes_io_name", "job", "deployment", "namespace") or "unknown",
                title=title,
                message=_first(alert.annotations, "description", "summary", "message") or title,
                severity=parse_severity(labels.get("severity")),
                status=SignalStatus.RESOLVED if alert.status == "resolved" else SignalStatus.FIRING,
                trace_id=_first(labels, "trace_id") or _first(alert.annotations, "trace_id"),
                external_id=alert.fingerprint,
                labels=labels,
                raw=alert.model_dump(mode="json"),
            )
        )
    return signals


# Google Cloud Monitoring webhook (schema version 1.2)


class GcpResource(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class GcpIncident(BaseModel):
    model_config = ConfigDict(extra="allow")
    incident_id: str
    state: str
    summary: str | None = None
    policy_name: str | None = None
    condition_name: str | None = None
    resource: GcpResource = Field(default_factory=GcpResource)
    resource_display_name: str | None = None
    severity: str | None = None
    policy_user_labels: dict[str, str] = Field(default_factory=dict)


class GcpMonitoringPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str | None = None
    incident: GcpIncident


def from_gcp_monitoring(payload: GcpMonitoringPayload) -> list[AlertSignal]:
    inc = payload.incident
    labels = {**inc.resource.labels, **inc.policy_user_labels}
    service = (
        _first(labels, "service", "service_name", "container_name", "module_id", "function_name")
        or inc.resource_display_name
        or "unknown"
    )
    title = inc.policy_name or inc.condition_name or "GCP Monitoring alert"
    return [
        AlertSignal(
            source=AlertSource.GCP_MONITORING,
            service=service,
            title=title,
            message=inc.summary or title,
            severity=parse_severity(inc.severity),
            status=SignalStatus.RESOLVED if inc.state.lower() == "closed" else SignalStatus.FIRING,
            external_id=inc.incident_id,
            labels=labels,
            raw=payload.model_dump(mode="json"),
        )
    ]


# Generic JSON


class GenericAlert(BaseModel):
    service: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    message: str = Field(min_length=1, max_length=20_000)
    severity: str | None = None
    status: SignalStatus = SignalStatus.FIRING
    trace_id: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)
    labels: dict[str, str] = Field(default_factory=dict)


def from_generic(alert: GenericAlert) -> list[AlertSignal]:
    raw: dict[str, Any] = alert.model_dump(mode="json")
    return [
        AlertSignal(
            source=AlertSource.GENERIC,
            service=alert.service,
            title=alert.title,
            message=alert.message,
            severity=parse_severity(alert.severity),
            status=alert.status,
            trace_id=alert.trace_id,
            external_id=alert.external_id,
            labels=alert.labels,
            raw=raw,
        )
    ]
