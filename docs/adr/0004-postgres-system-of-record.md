# 0004. PostgreSQL as system of record

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype keeps state in Redis keys with a 5-minute TTL and in an in-memory set. There is no durable incident
history, audit trail, or approval state.

## Decision

We will use PostgreSQL (16+) as the system of record, accessed via SQLAlchemy 2.0 async (asyncpg driver) with
Alembic migrations. Core tables:

- `incidents` — id, fingerprint, service, severity, tier, status, title, rca_summary, ticket ref, timestamps, version (optimistic locking)
- `alert_signals` — raw normalized signals linked to an incident (dedup attaches new signals to an open incident)
- `incident_events` — append-only timeline / audit log of every state transition, tool call, and decision
- `remediation_actions` — proposed/executed actions, policy verdict, dry-run flag, result
- `approvals` — approval requests, approver, decision, expiry, signed-token hash
- `agent_runs` — model, prompt version, tokens, latency, outcome
- `api_clients` — webhook sources and hashed credentials

Redis remains for ephemeral data only (queue, dedup window, rate limits); losing Redis must not lose incidents.

## Alternatives considered

- **Redis only** — no relational queries, weak durability for audit.
- **Firestore / document DB** — weaker transactional guarantees across incident + timeline writes; cloud lock-in.

## Consequences

- Operational dependency on Postgres (Cloud SQL in GCP; container locally/CI).
- Migrations must follow expand → migrate → contract for zero-downtime deploys.
