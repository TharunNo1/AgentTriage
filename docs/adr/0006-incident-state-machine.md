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
                         │                  │             │
                         └──── rejected/expired ──────────┴──→ ESCALATED
TRIAGING ──(tier 3 / agent failure)──→ ESCALATED
any open state ──(manual)──→ RESOLVED | SUPPRESSED
```

- Tier (1/2/3) is produced by the agent but the *transition* is decided by code using the tier plus the safety policy (0008).
- Only the domain layer may change `incidents.status`; every transition writes an `incident_events` row in the same transaction.
- Duplicate signals for an open incident (same fingerprint) attach to it and increment its occurrence count instead of starting new triage.

## Alternatives considered

- **LLM-driven workflow (status quo)** — unpredictable, untestable, unsafe for remediation.

## Consequences

- Lifecycle is unit-testable and auditable; the LLM is confined to analysis and proposals.
