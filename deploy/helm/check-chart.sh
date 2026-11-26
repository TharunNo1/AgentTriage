#!/usr/bin/env bash
set -euo pipefail

chart="$(dirname "$0")/agent-triage"
image=(--set image.repository=example.invalid/agent-triage --set-string image.tag=ci)

for profile in dev staging production; do
  values=(-f "$chart/values-$profile.yaml")
  helm lint --strict "$chart" "${values[@]}" "${image[@]}"
  rendered=$(helm template triage "$chart" "${values[@]}" "${image[@]}")
  grep -Fq 'helm.sh/hook: pre-install,pre-upgrade' <<< "$rendered"
  grep -Fq 'httpGet: {path: /readyz, port: http}' <<< "$rendered"
  grep -Fq 'value: dry_run' <<< "$rendered"
  ! grep -Fxq '  name: triage-dashboard' <<< "$rendered" || exit 1
  if [[ "$profile" == dev ]]; then
    ! grep -Eq '^kind: (HorizontalPodAutoscaler|PodDisruptionBudget)$' <<< "$rendered" || exit 1
  else
    grep -Fxq 'kind: HorizontalPodAutoscaler' <<< "$rendered"
    grep -Fxq 'kind: PodDisruptionBudget' <<< "$rendered"
  fi
done

worker_hpa=$(helm template triage "$chart" "${image[@]}" \
  --set worker.autoscaling.enabled=true --set worker.autoscaling.metricName=arq_queue_depth)
grep -Fq 'name: "arq_queue_depth"' <<< "$worker_hpa"

if error=$(helm template triage "$chart" "${image[@]}" --set worker.autoscaling.enabled=true 2>&1); then
  echo 'Expected worker autoscaling without a metric name to fail' >&2
  exit 1
fi
grep -Fq 'worker.autoscaling.metricName is required when enabled' <<< "$error"

dashboard_chart="$(dirname "$0")/dashboard"
dashboard_values=(
  --set image=example.invalid/agent-triage-dashboard:ci
  --set apiUpstream=triage-api:8000
)
helm lint --strict "$dashboard_chart" "${dashboard_values[@]}"
if error=$(helm template dashboard "$dashboard_chart" "${dashboard_values[0]}" "${dashboard_values[1]}" 2>&1); then
  echo 'Expected installing the dashboard without an API upstream to fail' >&2
  exit 1
fi
grep -Fq 'apiUpstream is required' <<< "$error"

dashboard=$(helm template dashboard "$dashboard_chart" "${dashboard_values[@]}")
grep -Fxq 'kind: Deployment' <<< "$dashboard"
grep -Fxq 'kind: Service' <<< "$dashboard"
grep -Fq 'image: "example.invalid/agent-triage-dashboard:ci"' <<< "$dashboard"
grep -Fq 'value: "triage-api:8000"' <<< "$dashboard"
! grep -Eq 'secretKeyRef:|envFrom:|helm.sh/hook:' <<< "$dashboard" || exit 1
