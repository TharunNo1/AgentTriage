# 0014. Deliver incident notifications through the Resend email API

- Status: Proposed

## Context

Operators need email lifecycle notifications. A worker can lose the response after the provider accepts an email,
or fail to commit the incident timeline after acceptance. Retrying must limit duplicate sends in both cases.

## Decision

Add Resend as an opt-in worker notifier using the existing asynchronous HTTPX dependency. Use one verified sender
and one configured recipient. Send an event label and incident ID. Operators review incidents and submit approvals
through the authenticated API.

Derive the provider idempotency key from the existing arq job ID. Keep the payload stable across retries even if the
incident changes. Retry transient delivery failures within the worker retry budget and refuse to send jobs 23 hours
after enqueue, ahead of Resend's 24-hour key retention. An acknowledged send is recorded as a timeline event.
It indicates provider acceptance. If the sender or recipient changes while a job is retrying, the provider can reject
the changed payload for the original key. Use a dedicated sending key and keep credentials in worker secrets.

## Alternatives considered

- Send over SMTP. Standard SMTP acceptance does not deduplicate retries after a lost response.
- Add a local delivery record. It could track worker progress but cannot resolve an ambiguous provider response on its own.

## Consequences and validation

The default mock and the Slack option remain available. Select the previous notifier and restart workers to roll back.
Provider retention bounds deduplication, and separate jobs can send separate emails. Fake transport tests exercise
stable replay and response classification. Staging verification requires a verified sending domain and a test mailbox.
