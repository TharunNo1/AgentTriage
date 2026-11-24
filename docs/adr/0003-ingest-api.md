# 0003. Webhook ingest API

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype exposes `POST /triage` with no authentication and performs triage in-process via FastAPI
`BackgroundTasks`, which are lost on restart and cannot be scaled independently.

## Decision

We will build a stateless FastAPI ingest service that:

- Exposes versioned webhook receivers: `POST /v1/alerts/alertmanager`, `POST /v1/alerts/gcp-monitoring`,
  `POST /v1/alerts/generic`. Each adapter normalizes to an internal `AlertSignal` schema.
- Authenticates every webhook via HMAC-SHA256 signature (preferred) or per-source API key; keys are stored hashed.
- Enforces payload size limits and per-source rate limits (Redis).
- Is idempotent: computes a fingerprint and honours an `Idempotency-Key` header.
- Persists the signal, creates or attaches to an incident (see 0004, 0006), enqueues a triage job (see 0005), and
  returns `202 Accepted` with the `incident_id`. No LLM work happens in the request path.
- Exposes read APIs (`GET /v1/incidents`, `GET /v1/incidents/{id}`, timeline) and `/healthz`, `/readyz`, `/metrics`.
- Returns RFC 9457 problem-details errors.

## Alternatives considered

- **Keep synchronous triage in request** — LLM latency (seconds to minutes) and retries make this unsuitable.
- **Pub/Sub push as the only entrypoint** — ties us to one cloud; can be added later as another adapter.

## Consequences

- Ingest scales horizontally and stays fast; work is durable.
- Each new alert source is a small adapter + tests.
