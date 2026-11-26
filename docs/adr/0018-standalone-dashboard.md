# 0018. Deploy the dashboard independently of FastAPI

- Status: Proposed
- Date: 2026-11-26
- Deciders: Tharun

## Context

FastAPI currently serves the dashboard shell alongside its authenticated API. Operators need to build and deploy
the frontend independently. ADR 0017 defines dashboard permissions and the session API.

## Decision

Build the frontend from `frontend/` into its own unprivileged NGINX image. Serve HTML and static assets on port
8080. Proxy the dashboard session endpoint, incident API, and readiness checks to FastAPI on the browser's
origin. Terminate HTTPS at the deployment gateway. Keep API keys in browser memory. FastAPI owns authentication,
RBAC, no-store headers for incident data, and approval decisions.

Use semantic HTML and responsive CSS, and test keyboard access and narrow viewports. The frontend sets a Content
Security Policy and validates static assets on revisit. It uses browser APIs and needs no JavaScript build.

## Alternatives considered

- FastAPI packaging couples the frontend and backend release cycles.
- Direct cross-origin requests require a CORS policy, deployment-specific CSP, and exposure of a separate browser API origin.

## Consequences

The frontend has its own Helm chart. Frontend upgrades and rollbacks do not run backend migrations.
The dashboard session API remains opt-in.
The frontend needs an upstream address reachable from its runtime. The backend wheel and image exclude frontend
files. Ingest, API docs, and metrics continue to use the API service.
