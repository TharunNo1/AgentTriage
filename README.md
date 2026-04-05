Agent Triage
---
Agent Triage is an industry-grade autonomous SRE agent that leverages self-healing mechanisms to detect anomalies, perform root cause analysis, and execute remediation workflows in distributed systems.

🚀 Core Features
---
- **Autonomous Anomaly Detection:** Continuous monitoring of distributed traces and metrics to identify deviations before they become outages.


- **Intelligent RCA:** Leverages LLM-driven reasoning to correlate logs, metrics, and events to find the "smoking gun."


- **Self-Healing Workflows:** Automatically executes pre-defined or dynamically generated remediation scripts (e.g., clearing caches, scaling pods, or rolling back deployments).

🛠 Installation and Setup
---
1. Prerequisites
Ensure you have Docker and Python 3.10+ installed. This project uses uv for lightning-fast dependency management.


2. Start the Infrastructure
Agent Triage requires Redis for state management and task queuing.

    ```bash
    docker run -d --name redis-triage -p 6379:6379 redis:latest
    ```

3. Configure Environment
Copy the template and fill in your credentials (API keys, connection strings, etc.):

    ```bash
    cp .env.template .env
    ```

4. Start the Backend (FastAPI)
The backend handles the agent logic and orchestration.

    ```bash
    pip install uv
    uv sync
    uvicorn app.main:app --reload
    ```
5. Launch the Dashboard (Streamlit)
The UI provides a real-time view of agent activity and system health.

    ```bash
    python -m streamlit run app/demo/ui.py
    ```

🏗 System Architecture
---
The system operates on a closed-loop feedback mechanism:

- Observe: Collects telemetry from the distributed system.

- Orient: Detects anomalies and analyzes the impact.

- Decide: Performs RCA and selects a remediation strategy.

- Act: Executes the workflow and verifies system recovery.
