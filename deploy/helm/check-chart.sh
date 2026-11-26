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
