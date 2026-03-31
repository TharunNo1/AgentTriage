import os
import re

import streamlit as st
import httpx
import json

from app.config import settings

st.set_page_config(page_title="SRE Self-Healing Portal", layout="wide")

st.title("🤖 SRE Autonomous Triage Agent")
st.markdown("---")

# 1. Sidebar Inputs
with st.sidebar:
    st.header("Trigger the error trace in application")
    service_name = st.text_input("Service Name", value="payment-api")
    trace_id = st.text_input("Trace ID", value="tr-550e840")
    error_message = st.text_area("Error Signal", value="JSONDecodeError: Expecting value at line 1 column 1")
    trigger_btn = st.button("🚀 Start Triage", use_container_width=True)

# 2. Main UI Layout
thought_container = st.container(border=True)
if os.path.exists(settings.LOG_FILE_PATH):
    with open(settings.LOG_FILE_PATH, "r") as f:
        content = f.read()

    # 1. Split content by the Scenario Headers
    # This regex looks for the "--- SCENARIO: ... ---" pattern
    scenarios = re.split(r'(--- SCENARIO: .*? ---)', content)

    # scenarios[0] is usually empty or preamble, so we skip it
    # We iterate in steps of 2 to get [Header, Body] pairs
    for i in range(1, 5, 2):
        header = scenarios[i].strip()
        body = scenarios[i + 1].strip()

        # Extract Trace ID from header for the label
        trace_match = re.search(r'TRACE: ([\w-]+)', header)
        trace_id = trace_match.group(1) if trace_match else "Unknown"

        # 2. Render as a single integrated block
        with thought_container.expander(f"🕵️ {header}", expanded=(i == 1)):
            # Display the logs in a clean code block to preserve formatting
            st.code(body, language="log")

            # If you want to show a "Heal" button specifically for this trace
            if "ERROR" in body or "CRITICAL" in body:
                st.button(f"Retry Healing for {trace_id}", key=f"btn_{trace_id}")
else:
    thought_container.info("No trace logs found.")
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Thought Process & Logs")
    thought_container = st.container(border=True)

with col2:
    st.subheader("Final RCA & Action Plan")
    report_placeholder = st.container(border=True)

# 3. Execution Logic
if trigger_btn:
    full_response = ""

    # We use httpx to connect to your FastAPI server
    with httpx.stream(
            "POST",
            "http://localhost:8000/ui/triage",
            json={"service_name": service_name, "trace_id": trace_id, "message": error_message},
            timeout=None
    ) as response:

        # Initialize a variable outside the loop to track the active status container
        active_tool_status = None

        for line in response.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                print(payload)
                if payload["type"] == "tool":
                    # If there was a previous tool, mark it complete before starting a new one
                    if active_tool_status:
                        active_tool_status.update(state="complete")

                    # Create the new status container
                    active_tool_status = thought_container.status(
                        f"🛠️ Executing: {payload['name']}",
                        state="running"
                    )
                    active_tool_status.write(payload["args"])

                elif payload["type"] == "output":
                    # Update the status to complete and show the result inside or near it
                    if active_tool_status:
                        active_tool_status.write(f"✅ Result: {payload['result']}")
                        active_tool_status.update(state="complete", label=f"✅ Finished: {payload['name']}")
                        active_tool_status = None  # Reset for the next tool

                elif payload["type"] == "text":
                    # Ensure any dangling tool status is closed when text starts coming in
                    if active_tool_status:
                        active_tool_status.update(state="complete")
                        active_tool_status = None

                    full_response += payload["content"]
                    if payload["content"] == "OLD_ISSUE_TRIAGE":
                        formatted_markdown = """
                            - Incident ID: N/A
                            - Severity: N/A
                            - Service: N/A
                            - Tier: N/A
                            - RCA Summary: The system identified this as a duplicate or existing issue. No new analysis required.
                            - Action Taken: IGNORING_DUPLICATE
                            - Status: AUTO-RESOLVED
                            """
                        report_placeholder.markdown(formatted_markdown)
                        continue
                    try:
                        data = json.loads(full_response)
                        formatted_markdown = f"""
                        - Incident ID: {data.get('Incident ID', 'N/A')}
                        - Severity: {data.get('Severity', 'N/A')}
                        - Service: {data.get('Service', 'N/A')}
                        - Tier: {data.get('Tier', 'N/A')}
                        - RCA Summary: {data.get('RCA Summary', 'N/A')}
                        - Action Taken: {data.get('Action Taken', 'N/A')}
                        - Status: {data.get('Status', 'N/A')}
                        """
                        report_placeholder.markdown(formatted_markdown)
                    except json.JSONDecodeError:
                        report_placeholder.markdown("⏳ *Generating structured report...*")


    st.success("Triage Complete.")