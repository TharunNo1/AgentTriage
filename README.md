# Agent Triage

Autonomous SRE incident triage. Agent Triage receives alerts, deduplicates them into incidents, analyses each incident, and either remediates it within policy, asks a human for approval, or escalates it. Every state change is persisted and audited.

See [docs/architecture.md](docs/architecture.md) for the design, [docs/adr/](docs/adr/README.md) for architecture decisions, and [AGENTS.md](AGENTS.md) for contribution and coding standards.

> **Status: Phase 2 rollout.** Gemini analysis is opt-in. The default triage agent, ticketing, and notifications use deterministic adapters. Remediation is dry-run only. Slack and email notifications are opt-in. Jira Cloud ticketing is opt-in. Log and Kubernetes adapters are planned.

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

## Gemini analysis

To enable Gemini, set `TRIAGE_TRIAGE_AGENT=gemini`, `TRIAGE_GEMINI_MODEL` to a model that supports structured
output, and `TRIAGE_GEMINI_API_KEY` in the worker environment. Enable this only for incident data approved for
processing by Gemini. The worker sends bounded excerpts of alert messages, service and title, and operator feedback.
It records the analysis and escalates the incident for operator review. The mock agent remains the default.

Run `uv run pytest tests/evals` to replay structured triage responses offline.

## Slack notifications

Set `TRIAGE_NOTIFIER=slack` and configure `TRIAGE_SLACK_WEBHOOK_URL` as a worker secret for the destination channel.
Messages include the incident ID, severity, and event label. Use the operator API to review incidents and submit approvals.
Delivery retries can produce duplicate messages after an ambiguous network failure.

## Email notifications

Set `TRIAGE_NOTIFIER=resend` in the worker environment. Configure the secret `TRIAGE_RESEND_API_KEY`,
a verified sender in `TRIAGE_RESEND_FROM_EMAIL`, and one recipient in `TRIAGE_RESEND_TO_EMAIL`.
Emails contain an incident ID and event label. The incident API handles review and approvals.
See [ADR 0014](docs/adr/0014-resend-email-notifications.md) for delivery and retry behavior.

## Jira Cloud ticketing

Select `TRIAGE_TICKETING=jira` and configure the tenant URL, project key, issue type ID, and service account
credentials using the Jira variables in `.env.example`. Use a dedicated Jira project and approve transfer of
triage summaries before enabling the worker. Operators can recover a reserved ticket by attaching the label
`agent-triage-<incident UUID>` to a single issue in the configured project. Review
[ADR 0015](docs/adr/0015-jira-cloud-ticketing.md) for retry and rollback behavior. If the original job exhausted
its retries, a deployment administrator can enqueue a new sync job from a Jira-enabled worker:

```bash
docker compose -f deploy/docker-compose.yml exec -T worker python - "$INCIDENT_ID" <<'PY'
import asyncio
import sys
from uuid import UUID
from arq import create_pool
from arq.connections import RedisSettings
from app.core.settings import get_settings

async def main():
    redis = await create_pool(RedisSettings.from_dsn(str(get_settings().redis_url)))
    try:
        await redis.enqueue_job("sync_ticket", str(UUID(sys.argv[1])))
    finally:
        await redis.aclose()

asyncio.run(main())
PY
```

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
