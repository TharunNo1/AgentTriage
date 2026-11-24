# 0011. Operator dashboard

- Status: Proposed
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype ships a Streamlit demo UI. Production operators need incident lists, timelines, and approval actions.

## Decision

- Phase 1–3: no bespoke UI. Operators use the REST API, Slack (notifications and approvals), and Grafana dashboards.
- Phase 4: a React + TypeScript dashboard consuming the `/v1` API (incident list, timeline, approvals, policy view).
- The Streamlit demo is removed in Phase 1.

## Alternatives considered

- **Keep Streamlit** — quick, but limited auth, multi-user, and UX control for production.

## Consequences

- Faster path to a production backend; UI deferred.
