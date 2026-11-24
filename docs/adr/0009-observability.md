# 0009. Observability

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

An SRE tool must itself be highly observable; the prototype uses `print` and basic logging.

## Decision

- Structured JSON logging (`structlog`) with bound context: `incident_id`, `trace_id`, `service`, `job_id`, `request_id`.
- OpenTelemetry tracing for API, workers, DB, Redis, HTTP clients, and LLM calls; OTLP exporter (Cloud Trace in GCP).
- Prometheus metrics at `/metrics`: ingest rate, dedup ratio, queue depth/latency, job outcomes, incidents by
  status/tier, MTTR, remediation outcomes, LLM tokens/cost/latency.
- Grafana dashboards and alert rules are versioned under `deploy/observability/`.

## Consequences

- Consistent debugging across services; LLM cost visibility from day one.
