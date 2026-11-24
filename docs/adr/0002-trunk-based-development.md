# 0002. Trunk-based development and branch naming

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

We want fast integration, small PRs, and an always-releasable `main`, with multiple humans and AI agents contributing.

## Decision

We will use trunk-based development:

- `main` is the trunk, protected, always releasable; changes land only via PR with green CI, squash-merged.
- Short-lived branches from `main`: `feature/<slug>` (default), `fix/<slug>`, `chore/<slug>`, `docs/<slug>`.
  Agent-specific prefixes (e.g. `devin/`) are not used.
- Unfinished work merges behind configuration feature flags instead of living on long branches.
- Commit messages and PR titles follow Conventional Commits.

## Alternatives considered

- **GitFlow** — long-lived `develop`/release branches add merge overhead with no benefit for a continuously deployed service.

## Consequences

- Requires feature flags for partially built capabilities (e.g. real remediation executor).
- Conventional Commits enable automated changelogs/release notes later.
