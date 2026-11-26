# 0013. Send operator notifications through Slack incoming webhooks

- Status: Proposed

## Context

Phase 2 needs a delivery channel for incident lifecycle notifications. The worker already queues notifications and records
successful delivery in the incident timeline. Operators need the incident reference while alert content stays inside Agent Triage.

## Decision

Add an opt-in Slack adapter behind the existing notifier port. Store one channel-bound webhook URL in the worker's secret
configuration. Send the incident ID, severity, and a predefined event label using async HTTPX, which the repository already
uses for tests. The adapter accepts HTTPS Slack webhook URLs and disables redirects. Approval continues through the
authenticated incident API. The mock notifier remains the default.

Retry rate limits, server errors, and transport failures within the existing worker retry budget. Reject other responses
and log the failure with its incident ID. Delivery is best effort. If Slack accepts a request before the worker times out
or records success, a retry may post a duplicate. Incoming webhooks offer no request deduplication for this flow.

## Alternatives considered

- Use Slack's bot API. A bot token and channel selection would broaden permissions for this single-channel rollout.
- Use interactive Slack approvals. That requires its own authenticated callback and authorization design.

## Consequences and validation

Deployment needs one dedicated channel webhook and a worker restart. Roll back by switching the notifier to mock and
restarting the worker. Test the payload and failure behavior through a fake HTTP transport. Before enabling production
delivery, verify the channel and post an approved synthetic incident in a staging deployment.
