from prometheus_client import Counter, Histogram

# Keep labels bounded. Per-incident and per-request identifiers belong in structured logs.
SIGNALS_INGESTED = Counter("triage_signals_ingested_total", "Alert signals received", ["source", "outcome"])
INCIDENT_TRANSITIONS = Counter("triage_incident_transitions_total", "Incident state transitions", ["to_status"])
JOBS = Counter("triage_jobs_total", "Background job executions", ["job", "outcome"])
AGENT_LATENCY = Histogram("triage_agent_latency_seconds", "Triage agent run latency", ["agent"])
