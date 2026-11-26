---
name: agent-triage-pr
description: Prepare, open, or update an Agent Triage pull request, including low-level design, impacted areas, verification, and GitHub assignment.
---

# Prepare an Agent Triage PR

1. Read the repository's AGENTS.md and .github/pull_request_template.md. For an existing PR, confirm the base,
   head SHA, author, assignees, and current body. Review the diff against its base and preserve existing issue links,
   decisions, and contributor notes when editing the body.
2. Write the low-level design from the actual diff. Identify the entry point, call or data flow, configuration and
   persistence changes, and failure or retry behavior where relevant. For a documentation or tooling PR, describe how
   contributors use the change. Link the ADR for architectural decisions and state what the ADR leaves open.
3. List impacted areas by component and describe the observable impact. Cover API clients, workers, storage, external
   services, and operator workflows when affected. Describe compatibility, enablement, and rollback when applicable.
4. Use the agent-triage-review skill for a self-review. Record material findings and how they were addressed. Record
   checks actually run, including the environment and result. Leave CI and live integration checks unchecked until
   verified for the current head. Mark inapplicable checklist items with a brief reason.
5. When authorized to open or update the PR, use the template. Use the requested assignee or preserve the existing
   assignees. If none are set, assign the human PR author when assignable, then verify the GitHub assignee field.
   If no intended human is inferable, report that assignment needs an owner. Assignment does not request review.
6. Before handing off, follow the end-of-task cleanup in AGENTS.md. Verify that pushed commits and the PR are
   discoverable before removing the temporary checkout. Report clean-up exceptions in the handoff.
