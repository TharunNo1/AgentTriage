---
name: agent-triage-review
description: Review an Agent Triage change or pull request for regressions, safety policy, compatibility, test gaps, and release readiness.
---

# Review an Agent Triage change

Inspect the diff against its base, relevant callers, tests, and accepted ADRs. Use the PR description to understand
intent and use the code to verify it. Review the following when the diff affects them.

- Follow the normal entry point through failures, retries, and repeated delivery. Check incident transitions, atomic
  timeline writes, queue behavior, and side effects that might happen twice or go missing.
- Trace any remediation action to its policy gate. Check approval, dry-run, kill-switch behavior, and the treatment
  of model output and external data as untrusted.
- Verify compatibility for existing API clients, queued jobs, incident data, and deployments. Check backward-compatible
  migrations and dependency or configuration changes against the ADRs and examples.
- Compare test assertions to the promised behavior. Check that CI results belong to the current head and distinguish
  simulated integrations from live verification.

Present findings in severity order with a file and line, a concrete failure scenario, and the impact. If there are
no findings, say so and identify relevant gaps in verification. Keep findings separate from summary and checklist
status. Publish review feedback only when authorized.
