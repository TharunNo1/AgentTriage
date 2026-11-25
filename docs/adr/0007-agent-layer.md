# 0007. Agent layer: model-agnostic interface, Gemini default

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The prototype uses Google ADK with an `InMemoryRunner` recreated per request, a single prompt that also drives the
workflow, and free-text JSON output. We need reliable structured output, cost tracking, testability, and freedom to
change model providers.

## Decision

- Define an `LLMProvider` port in `app/agent` (structured generation with tool calling). Ship a Gemini implementation
  first (via `google-genai`); other providers can be added as adapters.
- The agent performs **analysis only**: gather evidence through read-only tools (logs, recent deploys, metrics),
  then return a validated Pydantic `TriageResult` (service, error class, severity, tier, RCA summary, evidence,
  proposed remediation). It does not create tickets, send emails, or execute commands itself — the worker does that
  based on the state machine (0006) and policy (0008).
- Prompts are versioned files; each agent run records model, prompt version, tokens, latency in `agent_runs`.
- Bounded execution: max tool calls, max tokens, wall-clock timeout per run.
- Log content is treated as untrusted; it is delimited in prompts and cannot alter tool allowlists or policy.
- An offline eval suite (`tests/evals`) of labelled incident scenarios gates prompt/model changes.

## Alternatives considered

- **Keep Google ADK** — fast to start, but couples orchestration to one framework and encourages the LLM to own the workflow.
- **LangChain / LangGraph** — large dependency surface; our orchestration is the deterministic state machine already.

## Consequences

- Deterministic side effects; the LLM can be swapped or mocked in tests.
- Slightly more code than using a framework's built-in runner.
