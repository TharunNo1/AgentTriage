# 0012. Roll out Gemini incident analysis in the worker

- Status: Proposed

## Context

ADR 0007 selects Gemini through the Google Gen AI SDK. The existing mock agent drives dry-run remediation. Phase 2
needs a way to verify the accuracy and cost of model analysis before introducing model-generated action proposals.

## Decision

Make Gemini analysis opt-in at worker startup and keep the mock as the default. Use the asynchronous Google Gen AI SDK
with one structured generation call, bounded evidence, a 30-second deadline, and a 2,048 output-token limit. Validate
output in the service and escalate successful Gemini analyses for operator review. Use the existing worker retry and
failure audit path for generation errors. The worker closes the SDK client on shutdown.

## Alternatives considered

- Launch analysis and action proposals together. This would couple model evaluation to the remediation workflow.
- Use the Gemini HTTP API directly. The SDK implements the provider contract selected in ADR 0007.

## Consequences

Operators must approve the transfer of incident excerpts to Gemini before enabling the worker setting. Offline replay
tests verify validation and escalation. A live smoke test with approved sample alerts is needed to assess model
classification quality and token use. Roll back by selecting the mock agent and restarting the worker. Evidence tools,
action proposals, and external ticketing and notification adapters are later Phase 2 slices.
