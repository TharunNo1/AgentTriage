# 0001. Record architecture decisions

- Status: Accepted
- Date: 2026-11-24
- Deciders: Tharun

## Context

The project is being rebuilt for production and is developed largely with AI coding agents. Agents have no memory of
past discussions; without a written record they re-litigate or silently contradict earlier decisions.

## Decision

We will record every significant architectural decision as an Architecture Decision Record (ADR) in `docs/adr/`,
following the format in `template.md` (lightweight Nygard style). `AGENTS.md` requires agents to read the ADRs and to
add or supersede an ADR whenever they make a decision covered by the policy there.

## Alternatives considered

- **Wiki / Notion pages** — drift from code, not reviewed in PRs, not visible to coding agents.
- **No formal record** — fastest short term, highest long-term cost.

## Consequences

- Decisions are reviewed in the same PR as the code that implements them.
- Small ongoing cost of writing ADRs.
