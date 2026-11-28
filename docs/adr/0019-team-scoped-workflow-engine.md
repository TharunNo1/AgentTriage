# 0019. A versioned workflow engine for team-owned records

- Status: Proposed
- Date: 2026-11-27
- Deciders: Pending review

## Context

One organization manages records across teams. A person can hold different roles in different teams. Incidents are the first record type. An access request is the proposed second example.

Today the incident service writes state and timeline events in PostgreSQL. Several paths enqueue subsequent work after the transaction closes. A process exit after an approval commits and before the enqueue can strand the approved action. The existing stuck-incident job requeues triage. The remediation worker also calls an executor between two transactions, leaving an ambiguous outcome if the worker exits after the external call. Both windows need explicit recovery rules. See the [workflow service](../../app/services/workflow.py) and [worker jobs](../../app/workers/main.py).

## Decision

We propose one application service for workflow commands. The API, worker, and timer handlers use the same transition rules. PostgreSQL owns committed state and pending work. Redis and arq deliver jobs by ID. The first release supports one active state per record, human decisions, conditional transitions, timers, and catalogued actions. Parallel branches and joins would require additional execution semantics.

### Definitions and records

| Object | Contract |
|---|---|
| Workflow version | Immutable on publication. Contains a typed field schema, initial state, named transitions, actor requirements, guards, deadlines, and references to versioned action handlers. |
| Record | Stable ID, owning team, optional assignee, pinned workflow version, current state, typed payload, and monotonically increasing revision. Keep incident-specific signals and remediation data in their existing tables. |
| Approval | Bound to one record, proposal revision, action parameters, requester, and database deadline. Changing the proposal invalidates its pending approval. |
| Command receipt | Unique caller and command ID, canonical request digest, record ID and resulting revision. Reuse with different content produces a conflict. |
| History and pending work | An ordered event sequence per record and durable work rows keyed by transition and effect identity. Timers carry the expected approval or state-entry ID so an old timer cannot affect a later visit to the same state. |

Publishing validates field references, reachability, terminal states, action schemas, and guard types. Guards use a bounded set of typed comparisons. Each command names a transition so the engine can resolve it deterministically. Reject ambiguous automatic branches and unbounded automatic cycles. A record remains on its published version until an authorized migration maps its state, fields, pending approvals, and timers in one audited transaction. Retain referenced handler versions while records or queued work depend on them.

### Authorization

Bind each human credential to a stable person ID and each integration credential to a service identity. Key rotation preserves identity. Configure trusted ingest routing to determine the owning team. Include that team in fingerprint uniqueness, mute keys, and deduplication so matching alerts from different teams stay isolated.

For each membership, intersect the role's permissions with the rights available to that team on this record. The owner gets the workflow's owner-team permissions. Other teams need a current explicit grant. Union the resulting permissions across memberships, then enforce credential scope, workflow conditions, and separation of duties. Assignment conveys responsibility only. A person who requested an action cannot approve it using another membership when independent approval is required.

Filter visibility in repository queries before pagination or aggregation. Apply the same predicate to direct reads, timelines, search, attachments, and exports as those surfaces are introduced. Return the same missing-record response for an invisible ID as for an absent ID. An authorized reader lacking action permission gets a forbidden response. Audit membership, sharing, transfer, and publication changes. Transfer requires explicit authority and revalidation of grants, assignment, and pending approvals.

### One command from request to commit

1. Validate the command, authenticate the caller, and start a PostgreSQL transaction. Lock the record. Authorize against current membership and grants. Serialize changes to the authorization evidence with the sensitive mutation, using shared locks on the applicable authority rows and conflicting locks for revocation. Keep a consistent lock order and retry deadlocks within a bounded budget.
2. For an authorized retry with an identical request, return the committed receipt. Otherwise compare the supplied expected revision with the locked record. Reject a stale revision, including when another approver or the expiry worker won the race. Evaluate deadlines using database time after acquiring the lock.
3. Evaluate the named transition against the pinned definition. Verify the exact proposal, actor, guard conditions, and approval requirements. Persist the new revision, approval disposition, audit event, command receipt, and pending work together. A failure writing any one rolls back the transaction.
4. Acknowledge the committed revision. A lost HTTP response can be retried with the same key. Recheck current visibility before disclosing any saved result. Separate authorization to read an outcome from permission to perform a new transition.

### Delivery, timers, and recovery

The dispatcher scans due PostgreSQL work in bounded batches, claims rows in short transactions, and enqueues IDs. Track the next eligible dispatch time until the work reaches a terminal disposition. Redis acceptance alone cannot complete the row. Concurrent dispatchers can skip locked queue rows. [PostgreSQL locking clauses](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE)

| Failure | Required outcome |
|---|---|
| Database commits while Redis is unavailable, or Redis loses a job | The due row survives. Redispatch after recovery. Surface the oldest overdue work age. |
| Two workers receive the same job | Claim by conditional update with lease and attempt token. Check the token on completion. A stale worker cannot overwrite a newer result. |
| Provider accepts the call and the worker crashes | Use the stable effect ID for provider idempotency within its documented window, or reconcile by external operation ID. If the outcome cannot be established, mark it uncertain and require an audited operator decision. Lease expiry alone cannot authorize replay of that effect. |
| Approval and expiry race, or an old timer fires | Both use the command transaction and the specific approval ID. A decision requires a pending approval still within deadline. Only one disposition can commit. |
| A downstream dependency remains unavailable | Use bounded backoff with jitter and explicit timeouts. On exhaustion expose failed work with a reason and an authorized recovery action. Apply the workflow's configured escalation transition where appropriate. |

The workflow engine may request a typed remediation through the existing policy boundary. Only the policy-gated executor path can act. Check current mode, kill switch, approval binding, and policy at dispatch. Authorized execution and subsequent verification are distinct events. A workflow publisher cannot grant an action handler new infrastructure privileges. See [ADR 0008](0008-remediation-safety-policy.md).

### Audit and operation

For every accepted command capture the actor ID, credential reference, contributing team and grant, authorization rule version, workflow version, old and new revision, action, reason, and correlation ID. Preserve versioned authorization evidence so later membership edits leave the decision explainable. Redact credentials and sensitive payload fields. Record denied attempts in restricted security logs. Restrict ordinary application roles to append-only access on audit tables. Privileged-database tamper resistance would also require an independently administered immutable copy with monitored export lag.

Monitor overdue work, approval deadline lag, oldest uncertain effect, retry exhaustion, and transaction conflicts. A recovery console should show the operation and evidence, who may reconcile it, and the result of that decision. After a database restore, suspend external dispatch while reconciling effects that may have completed beyond the restore point. Confirm recovery time, acceptable data loss, peak load, audit retention, and audit export authority before setting production targets.

### Migration and verification

1. Add tables and nullable references with compatible Alembic migrations. Assign team ownership through reviewed mappings for legacy records and clients. Restrict unmapped records to migration operators and count them before cutover. Existing operator keys require explicit team bindings.
2. Compare workflow decisions against recorded incident scenarios without dispatching effects. Keep one writer per record. Pilot the approval transition under a feature flag with test teams and the mock executor. Scope every read path before enabling real team data. Verify Redis dedup and mute keys alongside database queries.
3. Route a record to a single execution implementation for its lifetime or through an explicit migration. Rollback stops new enrollment and drains or pauses pending work. Keep scoped access enforced. Use an older writer for an enrolled record only after compatibility and pending-effect reconciliation are verified.
4. Test with PostgreSQL transactions, separate connections, and injected failures. Demonstrate one accepted decision under concurrent approval, rejection of a revoked approver, isolated cross-team search and dedup, recovery after queue loss, and safe handling of a crash after provider acceptance. Reconstruct one complete decision from audit data after changing the actor's membership. Repeat with an access request before declaring the engine general purpose.

## Alternatives considered

Extending the incident state machine for each new record type would be inexpensive initially, but would duplicate access and recovery rules. An external orchestrator would supply durable execution while adding another operational dependency and requiring coordination with the authoritative record transaction. The proposed design reuses the current database and queue.

## Consequences

Teams can introduce record types through reviewed definitions. The project takes ownership of publication validation, database contention, recovery tooling, and maintaining historical definitions. Acceptance depends on proving the failure cases above and deciding the audit threat model and recovery targets. The first pilot uses the incident lifecycle in [ADR 0006](0006-incident-state-machine.md).
