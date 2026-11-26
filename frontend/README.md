# Standalone Agent Triage dashboard

The browser uses one origin for assets and API calls. The frontend proxies only `/v1/dashboard/session`,
`/v1/incidents` and its subpaths, and `/readyz`. It does not receive database or webhook secrets.

## Local Compose

Set `TRIAGE_DASHBOARD_ENABLED=true` in the repository's `.env` and run
`docker compose -f deploy/docker-compose.yml --profile dashboard up --build`. Open
`http://localhost:8080/dashboard`. The port binds to the local interface. The API remains on port 8000.

## Build and deploy the frontend

Run `docker build -t agent-triage-dashboard frontend` from the repository root. Run the image on port 8080 and
set `TRIAGE_API_UPSTREAM` to a trusted internal FastAPI address such as `api:8000`. The frontend runtime must
be able to resolve that address. Set `TRIAGE_DASHBOARD_ENABLED=true` on the API. Terminate HTTPS at your gateway
and route the dashboard origin to the frontend service.

For Kubernetes, set `config.TRIAGE_DASHBOARD_ENABLED=true` on the backend release during initial setup.
Install the frontend as a separate Helm release. The example uses the API Service from the `triage` backend release
in the same namespace.

```bash
helm upgrade --install triage-dashboard deploy/helm/dashboard \
  --set image=registry.example.com/agent-triage-dashboard:VERSION \
  --set apiUpstream=triage-api:8000
```

Route your HTTPS ingress to the `triage-dashboard` service on port 8080. For local Kubernetes verification, use
`kubectl port-forward svc/triage-dashboard 8080:8080` and open `http://localhost:8080/dashboard`.

The frontend's `/healthz` checks its own availability. `/readyz` reports the API's dependency readiness.
See the [role matrix](../README.md#incident-operations-dashboard) for key provisioning and permissions.
