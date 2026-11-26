# 0015. Synchronize incident tickets to Jira Cloud

- Status: Proposed

## Context

Jira Cloud issue creation can succeed before the worker receives the response. Enhanced JQL search can lag behind
creation, so a missing search result cannot establish that the first request failed.

## Decision

Offer opt-in Jira Cloud ticketing with the existing HTTPX dependency. Use a tenant-specific service account with
permission to browse, create, and edit issues in one dedicated project. Configure the issue type by ID. The worker
owns the issue description and writes the incident ID, current status, and up to 2,000 characters of triage summary
or alert title. Operator notes belong in Jira comments.

Under the incident row lock, commit a single create reservation to the incident timeline before calling Jira. Tag
the issue with a deterministic incident label. When the local Jira reference is missing after a reservation,
search that project's label and link a unique match. Never issue another create request after the reservation.
A successful create or recovery stores the key and browse URL. Later sync jobs update the description without
appending comments.

## Alternatives considered

- Retry creation after an empty search. Search lag can produce a duplicate.
- Hold the incident row lock across the request. A timeout or crash still leaves the remote outcome uncertain.

## Consequences and validation

An attempt that stops after reservation can leave the incident without a ticket. After checking Jira for an existing
match, an operator can create or label the issue manually and let a subsequent sync link it. The reservation is
retained for audit and recovery. Roll back by restoring mock ticketing and restarting workers. Existing Jira references
remain visible. Verify Jira permissions, issue type fields, and label indexing in staging before enabling production.
Offline tests cover the lost response, overlapping jobs, and recovery after the label becomes visible.
