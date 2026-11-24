# 0008. Remediation safety policy

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

Automated remediation on production infrastructure is the highest-risk capability. The prototype relies on a regex
allowlist of shell command strings.

## Decision

- Remediations are typed actions, not shell strings: e.g. `RestartDeployment`, `ScaleDeployment`, `DeletePod`,
  `RollbackDeployment`, each with validated parameters.
- A policy engine evaluates every proposed action against a declarative YAML policy (per environment, per service):
  allowed actions, required tier, whether approval is required, blast-radius limits (max replicas delta, max pods,
  namespaces), cooldowns, and maintenance windows. The verdict (`ALLOW`, `REQUIRE_APPROVAL`, `DENY`) and reasons are
  persisted.
- Global controls: `REMEDIATION_MODE = disabled | dry_run | enabled` (default `dry_run`) and a runtime kill switch.
- Approvals use Slack interactive buttons or single-use, expiring signed links; approvals resume the incident via a job.
- Executors use the Kubernetes API (official Python client) with a least-privilege, namespaced ServiceAccount — never
  `subprocess`/shell.
- Every action is followed by a verification job; failed verification escalates.

## Alternatives considered

- **Regex allowlist of shell commands (status quo)** — easy to bypass, hard to reason about blast radius.
- **OPA/Rego** — powerful, but an extra service and language; can supersede this if policies outgrow YAML.

## Consequences

- Safe by default; enabling real remediation is an explicit configuration change per environment.
