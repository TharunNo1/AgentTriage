# 0020. Recover delivery of approved dry-run work

- Status: Proposed
- Date: 2026-11-28
- Deciders: Pending review

## Context

An API process can stop after committing an approval and before enqueueing its execution. The same gap exists between recording the action outcome and enqueueing verification. The existing stuck-incident scan covers new incidents. The first delivery milestone in [ADR 0019](0019-team-scoped-workflow-engine.md) addresses approved dry-run work.

## Decision

Store the next delivery time on the approved action in the same PostgreSQL transaction as the approval decision and timeline event. Try Redis immediately after commit. A worker also checks due actions at startup and every minute. Dispatchers claim up to 100 rows with row locks, advance their retry time, commit, and enqueue stable job IDs. Losing a job leaves the database work eligible again.

The execution worker rechecks the action and incident. It cancels the enrolled action and escalates if the worker's remediation mode has changed from dry run. A successful dry run schedules verification in the outcome transaction. Verification clears the delivery time when consuming the work. Both action completion and incoming signal timestamps use the PostgreSQL clock for verification.

## Alternatives considered

A generic outbox table would support other workflow effects but would need an independent effect lifecycle. The existing typed action already identifies the work and tracks its execution status. Scanning every historical approved action would introduce ambiguity about which operations can safely be replayed.

## Consequences

Delivery is at least once. Repeated dry-run attempts have no external effect, and the committed action status guards the timeline transition. Real external actions need provider idempotency or outcome reconciliation before enrollment. Notifications and automatic tier-one actions retain their existing delivery paths.

Apply migration 0002 and upgrade all workers before deploying the API that enrolls new approvals. Existing rows have a null deadline. To roll back, stop enrollment by restoring the previous API, drain enrolled actions with the new workers, and check for outstanding delivery times before removing the column. Review already-stranded legacy incidents individually.
