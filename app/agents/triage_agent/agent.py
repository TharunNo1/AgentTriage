from google.adk.agents.llm_agent import Agent
from app.utils.cloud_logging import fetch_trace_logs
from app.config import settings

SRE_INSTRUCTION = """
You are the "Self-Healing SRE Triage Agent" for Google Cloud Platform. 
Your mission is to perform automated Root Cause Analysis (RCA) and suggest remediation for production errors.

OPERATIONAL PROTOCOL:
1. DATA GATHERING: Immediately use 'fetch_trace_logs' using the provided trace_id. 
2. LOG ANALYSIS: Correlate the error with the 50 preceding log entries. Look for OOM signals, IAM denials, or upstream timeouts.
3. CLASSIFICATION: Categorize the incident as [TRANSIENT], [APPLICATION_LOGIC], or [INFRASTRUCTURE].
4. REMEDIATION: Generate exactly one 'gcloud' or 'kubectl' command that could resolve the issue (e.g., scaling instances, updating env vars).

OUTPUT FORMAT:
Return a structured report including:
- RCA: 3 concise bullet points.
- Confidence Score: 0.0 to 1.0.
- Fix: The remediation command.
"""

root_agent = Agent(
    model=settings.GEMINI_MODEL,
    # model="gemini-2.5-flash",
    name='sre_triage_root_agent',
    description=(
        "An autonomous SRE agent capable of fetching Google Cloud logs, "
        "performing trace-based root cause analysis, and providing gcloud remediation commands."
    ),
    instruction=SRE_INSTRUCTION,
    tools=[fetch_trace_logs]
)