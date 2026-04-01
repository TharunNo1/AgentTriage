import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

Status = Literal["NEW", "ALREADY_EXISTS", "ERROR"]


def sync_jira_issue(
    service_name: str | None = None,
    error_code: str | None = None,
    resource_id: str | None = None,
    rca_summary: str | None = None,
    severity: str | None = None,
    trace_id: str | None = None,
    raw_logs: list[str] | None = None,
) -> dict[Any, Any]:
    """
    Mock Jira sync. Simulates ticket creation and deduplication.

    Returns ALREADY_EXISTS if a ticket for this service+error was
    seen in the same session, otherwise NEW.

    Args:
        service_name:  Affected service name.
        error_code:    The specific error code (e.g. OOMKilled, 504).
        resource_id:   The GCP resource identifier.
        rca_summary:   Root cause summary in ≤50 words.
        severity:      P0 | P1 | P2
        trace_id:      Unique trace identifier.
        raw_logs:      Optional list of raw log lines to attach.

    Returns:
        dict:
            status      (str)  — NEW | ALREADY_EXISTS | ERROR
            ticket_id   (str)  — e.g. SRE-4821
            ticket_url  (str)  — fake browse URL
            action      (str)  — what the mock did
    """
    try:
        if service_name is None:
            return {
                "status": "ERROR",
                "ticket_id": None,
                "ticket_url": None,
                "action": "Service Name is required for creating JIRA issue",
            }
        if error_code is None:
            error_code = ""
        ticket_id = f"SRE-{hash(service_name + error_code) % 9000 + 1000}"
        ticket_url = f"https://triage.atlassian.net/browse/{ticket_id}"
        dedup_key = f"{service_name}:{error_code}"

        # ── Simulate deduplication via module-level seen set ─────────────────
        if dedup_key in _seen_tickets:
            logger.info(f"[JIRA MOCK] ALREADY_EXISTS {ticket_id} — appending trace {trace_id}")
            return {
                "status": "ALREADY_EXISTS",
                "ticket_id": ticket_id,
                "ticket_url": ticket_url,
                "action": f"Appended trace_id={trace_id} to existing ticket comments.",
            }

        _seen_tickets.add(dedup_key)
        logger.info(f"[JIRA MOCK] NEW ticket {ticket_id} created for {service_name}/{error_code}")
        return {
            "status": "NEW",
            "ticket_id": ticket_id,
            "ticket_url": ticket_url,
            "action": f"Created High-Priority ticket {ticket_id} with severity={severity}.",
        }

    except Exception as e:
        logger.exception("sync_jira_issue mock: unexpected error")
        return {
            "status": "ERROR",
            "ticket_id": None,
            "ticket_url": None,
            "action": f"Mock failed unexpectedly: {e}",
        }


# Module-level dedup store — resets on process restart (mock only)
_seen_tickets: set[str] = set()
