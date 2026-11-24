# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. Read this file fully before making changes.

## Project

Agent Triage is an autonomous SRE incident-triage platform. It ingests alerts, deduplicates them, runs an LLM agent to
perform root cause analysis, files/updates tickets, and executes policy-gated remediation with human approval where
required. See `docs/architecture.md` for the system design and `docs/adr/` for every architectural decision.

## Golden rules

1. **Decisions live in ADRs.** Any change to architecture, a new runtime dependency, a new external integration, a new
   datastore, or a change to safety policy semantics requires a new ADR (or a superseding one) in the same PR.
   Do not silently contradict an `Accepted` ADR — supersede it.
2. **Small, reviewable PRs.** One logical change per PR. Prefer < 400 changed lines excluding lockfiles/generated code.
3. **Tests ship with code.** Every behavior change includes tests. Bug fixes start with a failing test.
4. **Never weaken safety.** Do not bypass the remediation policy engine, approval flow, dry-run mode, or kill switch,
   even in tests or "temporary" code. Remediation executors must only be reachable through the policy engine.
5. **No secrets in code.** Secrets come from environment / secret manager only. No default secret values in `Settings`.
6. **Keep the docs true.** If you change behavior described in `docs/` or this file, update them in the same PR.

## Branching and commits (trunk-based)

- `main` is the trunk and is always releasable. Never push directly to `main`; merge via PR with green CI.
- Branches are short-lived (ideally < 2 days) and branch from latest `main`:
  - `feature/<slug>` — new functionality (default)
  - `fix/<slug>` — bug fixes
  - `chore/<slug>` — tooling, deps, CI, refactors without behavior change
  - `docs/<slug>` — documentation / ADR-only changes
- Incomplete features merge behind a feature flag (config setting) rather than living on long branches.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(ingest): add alertmanager webhook`, `fix(worker): retry on redis timeout`, `docs(adr): 0007 agent layer`.
- Rebase on `main` before merge; squash-merge PRs.

## Repository layout (target, from Phase 1)

```
app/
  api/            # FastAPI routers, request/response schemas, auth, dependencies
  core/           # settings, logging, telemetry, errors — no business logic
  domain/         # pure business logic: incident state machine, fingerprinting, policies (no I/O)
  db/             # SQLAlchemy models, repositories, session management
  workers/        # arq worker settings and job functions
  agent/          # LLM provider interface, prompts, agent orchestration
  integrations/   # adapters behind ports: logs/, ticketing/, notify/, remediation/
migrations/       # Alembic migrations
tests/
  unit/           # no network, no containers; fast
  integration/    # real Postgres/Redis via testcontainers
  evals/          # agent/prompt evaluation datasets and runners
deploy/           # Dockerfile, docker-compose, Helm chart
docs/
  architecture.md
  adr/
```

Dependency direction: `api` / `workers` → `domain` ← `db` / `integrations` / `agent`. `domain` imports nothing from
the outer layers (ports-and-adapters). Integrations are accessed through `Protocol` interfaces defined in `domain`.

## Commands

```bash
uv sync --all-extras --dev          # install
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest tests/unit            # fast
uv run pytest                       # full (needs Docker for testcontainers)
pre-commit run --all-files          # run before every commit
docker compose -f deploy/docker-compose.yml up   # local stack (from Phase 1)
```

All of the above must pass before opening a PR.

## Coding standards

### Python
- Python 3.13, managed with `uv`. Add deps with `uv add`; commit `uv.lock`. Pin lower bounds; avoid brand-new releases.
- Ruff for lint + format (line length 130). Mypy in strict mode for `app/` — no untyped defs, no bare `Any` in
  public signatures, no `# type: ignore` without an error code and reason.
- Fully async I/O in request and worker paths. Never call blocking clients (sync SMTP, sync SDKs) on the event loop —
  use async clients or `asyncio.to_thread`.
- Pydantic v2 models at boundaries (API, queue payloads, LLM tool I/O). Dataclasses or plain classes in `domain`.
- Dependency injection via FastAPI `Depends` and app-lifespan singletons. No module-level clients created at import
  time; no per-request construction of expensive clients (DB engine, Redis pool, LLM runner).
- Configuration only via `app.core.settings` (pydantic-settings). No `os.getenv` elsewhere.
- Errors: raise domain exceptions; map them to HTTP responses in one place. Never swallow exceptions silently.
- No `print`. Use the structured logger; include `incident_id`, `trace_id`, `service` as bound context.
- Keep functions small and side effects explicit. Prefer composition over inheritance.
- Comments explain *why*, not *what*. Public functions get a one-line docstring when the name isn't enough.

### API
- Versioned routes under `/v1`. Breaking changes require a new version.
- Mutating endpoints accept an `Idempotency-Key` header or derive one from the payload.
- Webhooks are authenticated (HMAC signature or API key). Unauthenticated endpoints: `/healthz`, `/readyz`, `/metrics` only.
- Return RFC 9457 problem-details JSON for errors.

### Database
- Schema changes only via Alembic migrations; migrations must be backward compatible with the previous app version
  (expand → migrate → contract).
- Use repositories in `app/db/`; no raw SQL in routers or workers.
- Every state transition on an incident writes an audit/timeline row in the same transaction.

### Workers and jobs
- Jobs must be idempotent and safe to retry. Pass IDs, not large payloads; re-read state from Postgres.
- Every job has an explicit timeout and retry policy.

### Agent / LLM
- Prompts live in versioned files under `app/agent/prompts/`; prompt changes are code changes and require evals to pass.
- LLM output that drives actions must be parsed into a Pydantic schema and validated; never `eval`/execute raw model text.
- Tools exposed to the agent are thin wrappers over integration ports; side-effecting tools go through the policy engine.
- Record model, prompt version, token usage, and latency for every agent run.

### Testing
- Unit tests for all `domain` logic (target ≥ 90% coverage on `domain`). Integration tests for repositories, queue, and
  API flows using testcontainers. External SaaS (Jira, Slack, GCP) is faked at the port boundary — never called in CI.
- Agent changes are covered by `tests/evals` scenarios with expected tier/classification.
- Tests are deterministic: freeze time, seed randomness, no sleeps.

### Security
- Least-privilege credentials per integration; Kubernetes executor uses a dedicated ServiceAccount with namespaced RBAC.
- Validate and size-limit all inbound payloads. Treat log content as untrusted input to the LLM (prompt injection):
  never let log text change policy, tool allowlists, or approval requirements.
- Dependabot/CodeQL findings are fixed or explicitly triaged before merge.

## ADR process

- ADRs live in `docs/adr/NNNN-kebab-title.md`, numbered sequentially, using `docs/adr/template.md`.
- Status lifecycle: `Proposed` → `Accepted` → (`Deprecated` | `Superseded by NNNN`).
- ADRs are immutable once `Accepted`, except for status changes and typo fixes. To change a decision, write a new ADR.
- Update the index in `docs/adr/README.md` in the same PR.

## Definition of done

- [ ] Lint, format, mypy, tests pass locally and in CI
- [ ] Tests added/updated; evals pass for agent changes
- [ ] ADR added/updated if a decision was made
- [ ] `docs/` and this file updated if behavior or workflow changed
- [ ] New config documented in `.env.example` with no real secrets
- [ ] Logs/metrics added for new failure modes
