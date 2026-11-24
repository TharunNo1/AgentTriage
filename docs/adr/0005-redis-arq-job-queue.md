# 0005. Redis + arq for background jobs

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

Triage, remediation, verification, and approval-timeout handling are long-running, failure-prone, and must survive
restarts and scale independently from ingest.

## Decision

We will run background work in separate worker processes using [arq](https://github.com/python-arq/arq) on Redis:

- Jobs: `triage_incident`, `execute_remediation`, `verify_remediation`, `expire_approval`, `notify`.
- Jobs receive IDs only and re-read state from Postgres; they are idempotent and use optimistic locking on `incidents.version`.
- Each job has an explicit timeout, max tries, and exponential backoff; exhausted jobs move the incident to `ESCALATED`.
- Deferred jobs implement delays (e.g. verify after N seconds) instead of sleeping inside the agent.
- Redis also stores dedup windows (`SET NX EX`) and rate-limit counters.
- Workers scale horizontally (Kubernetes HPA on queue depth).

## Alternatives considered

- **Celery** — mature but sync-first, heavier; our stack is async.
- **Temporal** — excellent durable workflows but significant operational overhead for current scale; revisit if
  workflows grow complex (could supersede this ADR).
- **Cloud Tasks / Pub/Sub** — cloud lock-in, harder local dev.

## Consequences

- Simple async-native workers sharing code with the API.
- Redis must be highly available (Memorystore) — but it holds no system-of-record data.
