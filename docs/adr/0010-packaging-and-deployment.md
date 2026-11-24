# 0010. Packaging and deployment

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype is started manually with `uvicorn` and a hand-run Redis container.

## Decision

- One container image (multi-stage, `uv`, non-root, distroless/slim base) with two entrypoints: `api` and `worker`.
- `deploy/docker-compose.yml` for local dev: api, worker, postgres, redis, and optional observability stack.
- Helm chart for Kubernetes (GKE): separate Deployments for api and worker, HPA (CPU for api, queue depth for workers),
  PodDisruptionBudgets, probes, migration Job as a pre-upgrade hook.
- CI (GitHub Actions): ruff, mypy, unit + integration tests (testcontainers), evals, image build, Trivy scan;
  publish image on merge to `main`.
- Secrets via environment variables sourced from a secret manager (GCP Secret Manager / External Secrets).

## Consequences

- Same artifact runs locally, in CI, and in production.
