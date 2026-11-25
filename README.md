# Agent Triage

Autonomous SRE incident triage. Agent Triage receives alerts, deduplicates them into incidents, analyses each incident, and either remediates it within policy, asks a human for approval, or escalates it. Every state change is persisted and audited.

See [docs/architecture.md](docs/architecture.md) for the design, [docs/adr/](docs/adr/README.md) for architecture decisions, and [AGENTS.md](AGENTS.md) for contribution and coding standards.

> **Status: Phase 1 (core platform).** The triage agent, ticketing, notifications and remediation run behind interfaces with deterministic mock adapters. Remediation is dry-run only. Real Gemini, Jira, Slack and Kubernetes adapters land in phases 2 and 3.

## How it works

```text
Alertmanager / GCP Monitoring / generic JSON
  → POST /v1/alerts/*   (API key or HMAC, size limit, rate limit, idempotency)
  → fingerprint + dedup into one open incident per failure (Postgres)
  → arq worker: triage → AWAITING_APPROVAL | REMEDIATING | ESCALATED
  → remediation (dry-run) → VERIFYING → RESOLVED | ESCALATED
```

Approval rejections route by reason: `false_positive` → `SUPPRESSED` (fingerprint muted), `handle_manually` → `MANUAL` (assigned to the approver), `wrong_action` → re-triage once with the operator's note. See [ADR 0006](docs/adr/0006-incident-state-machine.md).

## Quick start (Docker)

```bash
docker compose -f deploy/docker-compose.yml up --build -d
# create API keys (printed once)
docker compose -f deploy/docker-compose.yml exec api agent-triage create-api-key --name alertmanager --scopes ingest
docker compose -f deploy/docker-compose.yml exec api agent-triage create-api-key --name oncall --scopes operator

curl -X POST localhost:8000/v1/alerts/generic \
  -H "Authorization: Bearer $INGEST_KEY" -H "Content-Type: application/json" \
  -d '{"service":"checkout","title":"Pod crash","message":"container OOMKilled exit code 137"}'
curl localhost:8000/v1/incidents -H "Authorization: Bearer $OPERATOR_KEY"
```

OpenAPI docs are served at `http://localhost:8000/docs`; Prometheus metrics at `/metrics`.

## API

| Method | Path | Scope | Purpose |
|---|---|---|---|
| POST | `/v1/alerts/alertmanager` | ingest | Alertmanager webhook (v4) |
| POST | `/v1/alerts/gcp-monitoring` | ingest | Cloud Monitoring webhook |
| POST | `/v1/alerts/generic` | ingest | Generic JSON alert |
| GET | `/v1/incidents` | operator | List incidents (cursor pagination, `status`, `service` filters) |
| GET | `/v1/incidents/{id}` | operator | Incident detail |
| GET | `/v1/incidents/{id}/events` | operator | Audit timeline |
| POST | `/v1/incidents/{id}/approval` | operator | `{"decision":"approve"}` or `{"decision":"reject","reason":"false_positive\|handle_manually\|wrong_action"}` |
| POST | `/v1/incidents/{id}/transition` | operator | Manually move to `RESOLVED`, `SUPPRESSED` or `MANUAL` |
| GET | `/healthz`, `/readyz`, `/metrics` | none | Liveness, readiness, metrics |

**Authentication:** `Authorization: Bearer <api key>` (keys are stored hashed), or for webhook senders that cannot set bearer tokens, HMAC: `X-Triage-Client`, `X-Triage-Timestamp` (unix seconds) and `X-Triage-Signature: sha256=hex(HMAC(secret, "<timestamp>.<raw body>"))`, with secrets in `TRIAGE_WEBHOOK_HMAC_SECRETS`. Send `Idempotency-Key` to make retries safe. Errors are `application/problem+json`.

## Development

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync --all-groups
pre-commit install
cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d postgres redis
uv run alembic upgrade head
uv run uvicorn app.api.main:create_app --factory --reload   # API
uv run arq app.workers.main.WorkerSettings                  # worker

uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest            # unit + integration (integration tests start Postgres/Redis via testcontainers)
uv run pytest tests/unit # fast, no Docker
```

Configuration is environment-driven (`TRIAGE_*`); see [.env.example](.env.example) and `app/core/settings.py`.

## License

See [LICENSE](LICENSE).
