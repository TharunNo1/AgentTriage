# 0006. Incident lifecycle state machine

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype encodes the workflow only in an LLM prompt, so the actual lifecycle is non-deterministic and unobservable.

## Decision

The incident lifecycle is an explicit, deterministic state machine in `app/domain`, independent of the LLM:

```
NEW → TRIAGING → (AWAITING_APPROVAL) → REMEDIATING → VERIFYING → RESOLVED
         │              │                                 │
         │              ├─ rejected: false_positive ──→ SUPPRESSED
         │              ├─ rejected: handle_manually ─→ MANUAL ──→ RESOLVED
         │              ├─ rejected: wrong_action ────→ TRIAGING (re-propose, max 1, else MANUAL)
         │              └─ expired (no response) ─────→ ESCALATED
         │                                                 │
         └──(tier 3 / agent failure)──→ ESCALATED ←──(verification failed)
any open state ──(manual)──→ RESOLVED | SUPPRESSED | MANUAL
```

- Rejecting an approval is a human decision, not a failure, so it does not page anyone. The approver must pick a
  reason, and the reason decides the next state:
  - `false_positive` → `SUPPRESSED`; the fingerprint is muted for a configurable window.
  - `handle_manually` → `MANUAL`; the incident is assigned to the approver, the ticket is updated, and automation stops.
  - `wrong_action` → back to `TRIAGING` with the rejection note as agent context; after one re-proposal it goes to `MANUAL`.
- `ESCALATED` (pages on-call) is reserved for cases where no human owns the incident: approval expired unanswered,
  tier 3, agent failure, or failed verification.
- Tier (1/2/3) is produced by the agent but the *transition* is decided by code using the tier plus the safety policy (0008).
- Only the domain layer may change `incidents.status`; every transition writes an `incident_events` row in the same transaction.
- Duplicate signals for an open incident (same fingerprint) attach to it and increment its occurrence count instead of starting new triage.

## Alternatives considered

- **LLM-driven workflow (status quo)** — unpredictable, untestable, unsafe for remediation.

## Consequences

- Lifecycle is unit-testable and auditable; the LLM is confined to analysis and proposals.
