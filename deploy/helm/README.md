# Kubernetes deployment

The chart runs the API, arq worker, and Alembic migration Job from one container image. The API is available inside the
cluster on port 8000. All profiles set remediation mode to `dry_run` and disable Pod service account token mounting.

| Profile | Application environment | API replicas | Worker replicas |
| --- | --- | --- | --- |
| `dev` | `local` | 1 | 1 |
| `staging` | `staging` | 2–3 via CPU HPA | 2 |
| `production` | `production` | 3–10 via CPU HPA | 3 |

Staging and production set a PodDisruptionBudget for each workload. CPU autoscaling needs the Kubernetes resource
metrics API. Worker autoscaling is opt-in. Set `worker.autoscaling.enabled=true` and set
`worker.autoscaling.metricName` to the ARQ queue-depth metric provided by your cluster's external metrics adapter.
The adapter must scope the metric to the Redis queue for this release. Use separate databases and Redis queues per
environment.

## Install or upgrade

1. Select the Kubernetes context and create a namespace for the environment.
2. Provision PostgreSQL and Redis reachable from that namespace. Use your secret manager to populate the namespace
   Secret `agent-triage-runtime` (or set `existingSecret`). Include `TRIAGE_DATABASE_URL` with a
   `postgresql+asyncpg://` DSN and `TRIAGE_REDIS_URL`. Add any enabled integration credentials or webhook HMAC secrets
   using the keys in `.env.example`. Put non-secret application settings under `config`.
3. Build the repository Dockerfile and publish the image to a registry the cluster can pull from. For a private
   registry, supply `image.pullSecrets` with references to pull Secrets in the same namespace.
4. Run the command below with the registry path and immutable image tag. For dev or production, switch the namespace
   and values file together.

```sh
helm upgrade --install triage deploy/helm/agent-triage \
  --kube-context YOUR_CONTEXT --namespace triage-staging \
  -f deploy/helm/agent-triage/values-staging.yaml \
  --set image.repository=YOUR_REGISTRY/agent-triage \
  --set-string image.tag=YOUR_IMAGE_TAG \
  --atomic --timeout 10m
```

Alembic runs before install and upgrade. A failed migration blocks the rollout. Helm rollback does not reverse
database migrations, so migrations must remain compatible with the previous app version. Rotate application Secrets
by restarting the API and worker Deployments after the new Secret values are available.

From the repository root, run `bash deploy/helm/check-chart.sh` with Helm on `PATH` to validate all three profiles.

## Validate on Minikube

Run these commands from the repository root in Bash or Git Bash with Docker, Minikube, `kubectl`, and Helm available.
They use the default `minikube` profile and create
disposable PostgreSQL and Redis pods with a local test password. Namespace cleanup deletes their data.

```bash
minikube start
kubectl --context minikube create namespace triage-dev
k() { kubectl --context minikube --namespace triage-dev "$@"; }

k run postgres --image=postgres:16-alpine --port=5432 \
  --env=POSTGRES_USER=triage --env=POSTGRES_PASSWORD=triage --env=POSTGRES_DB=triage
k run redis --image=redis:7-alpine --port=6379
k expose pod postgres --port=5432
k expose pod redis --port=6379
k wait --for=condition=Ready pod/postgres pod/redis --timeout=120s
# Wait for PostgreSQL to accept TCP connections after database initialization.
for attempt in {1..30}; do
  if k exec postgres -- pg_isready -h 127.0.0.1 -U triage -d triage; then break; fi
  sleep 2
done
k exec postgres -- pg_isready -h 127.0.0.1 -U triage -d triage
k exec redis -- redis-cli ping

k create secret generic agent-triage-runtime \
  --from-literal=TRIAGE_DATABASE_URL=postgresql+asyncpg://triage:triage@postgres:5432/triage \
  --from-literal=TRIAGE_REDIS_URL=redis://redis:6379/0

tag="dev-$(git rev-parse --short HEAD)"
docker build -t "agent-triage:$tag" .
minikube image load "agent-triage:$tag"
helm upgrade --install triage deploy/helm/agent-triage \
  --kube-context minikube --namespace triage-dev \
  -f deploy/helm/agent-triage/values-dev.yaml \
  --set image.repository=agent-triage --set-string image.tag="$tag" \
  --wait --timeout 10m

k rollout status deployment/triage-api --timeout=120s
k rollout status deployment/triage-worker --timeout=120s
k exec deployment/triage-api -- alembic current
k logs deployment/triage-worker --tail=50
k port-forward svc/triage-api 8000:8000
```

`alembic current` should report a revision marked `(head)`. Look for `worker_started` in the worker logs. While port
forwarding is active, run these checks in another terminal. Both should return HTTP 200, with the readiness response
reporting `database` and `redis` as `ok`.

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
```

Rerun the same Helm command to check the upgrade path. Helm removes successful migration Jobs. If a migration fails,
inspect it with `k logs job/triage-migrate` before retrying. For staging or production profile smoke tests, enable
`minikube addons enable metrics-server`, then select the corresponding values file and check `k get hpa,pdb`.

Stop port forwarding with Ctrl+C and remove the disposable namespace when finished.

```bash
kubectl --context minikube delete namespace triage-dev
```
