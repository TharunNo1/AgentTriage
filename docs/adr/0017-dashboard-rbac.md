# 0017. Dashboard and incident role-based access

- Status: Proposed
- Date: 2026-11-26
- Deciders: Tharun

The packaging decision below is revised by [ADR 0018](0018-standalone-dashboard.md). This ADR describes RBAC.

## Context

ADR 0011 deferred the UI to Phase 4 and selected React and TypeScript. Incident API access currently uses the ingest
and operator scopes. People who monitor incidents need narrower access than people who manage or approve them.

## Decision

Use an opt-in, same-origin dashboard served by FastAPI with HTML, CSS, and browser JavaScript. This proposes replacing
the Phase 4 React implementation decision in ADR 0011. The public sign-in shell and its assets contain no incident data.
It sends an in-memory API key in the Authorization header over the existing bearer authentication flow.

Map stored scopes to permissions on every incident API request. Viewer, responder, approver, and operator can read
incident data. Responder and operator can change incident status, which can close a pending approval through the
existing workflow. Approver and operator can decide approvals. Ingest grants alert submission only. Existing operator
and ingest keys retain their original capabilities. Credentials remain scoped and revocable via the existing CLI.

Approval decisions submitted by the dashboard identify the exact approval displayed. The workflow checks that approval
under the incident lock, including its expiry, before recording the decision. The existing decision payload also remains
supported for API clients. Remediation mode is displayed from API settings and execution stays on the existing workflow.

## Alternatives considered

- A React build would introduce a separate frontend dependency and build pipeline for this first dashboard slice.
- Identity-provider integration would support organization-managed identity and credentials and requires a provider
  and an agreed group mapping.

## Consequences

The dashboard ships with the API image and is disabled by default. The roles apply platform-wide. API keys must be
provisioned and rotated by the deployment operator. The dashboard shows API readiness and incident activity.
