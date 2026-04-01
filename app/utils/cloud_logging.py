import os.path
import uuid
from datetime import datetime, timedelta
from typing import Any

from google.cloud import logging_v2
from google.cloud.logging_v2 import Client

from app.config import settings


def get_timestamp(offset_seconds: int = 0) -> str:
    return str((datetime.now() + timedelta(seconds=offset_seconds)).strftime("%H:%M:%S"))


def get_sre_log_source() -> dict[str, Any]:
    def trace_id() -> str:
        return f"tr-{uuid.uuid4().hex[:6]}"

    return {
        "DB_DEADLOCK": {
            "trace_id": trace_id(),
            "description": "Database transaction deadlock during high concurrency.",
            "logs": [
                f"[{get_timestamp(-10)}] [INFO] Begin transaction: Update Inventory",
                f"[{get_timestamp(-8)}] [DEBUG] Attempting Row Lock on ID: 5501",
                f"[{get_timestamp(-5)}] [WARNING] Lock wait timeout exceeded (5000ms). Retrying...",
                f"[{get_timestamp()}] [ERROR] Deadlock found when trying to get lock; try restarting transaction",
                f"[{get_timestamp()}] [CRITICAL] sqlalchemy.exc.InternalError: (1213, 'Deadlock found')",
            ],
        },
        "IAM_PERMISSION_DENIED": {
            "trace_id": trace_id(),
            "description": "Service Account missing storage.objects.create permission.",
            "logs": [
                f"[{get_timestamp(-5)}] [INFO] Initializing GCS Client for bucket: 'user-uploads'",
                f"[{get_timestamp(-3)}] [DEBUG] Uploading blob: 'profile_99.png'",
                f"[{get_timestamp()}] [ERROR] 403 Forbidden: service-account@project.iam.gserviceaccount.com "
                + "does not have storage.objects.create access.",
            ],
        },
        "MEMORY_LEAK_OOM": {
            "trace_id": trace_id(),
            "description": "Application memory exhausted leading to SIGKILL.",
            "logs": [
                f"[{get_timestamp(-60)}] [DEBUG] Memory: 256MB / 512MB",
                f"[{get_timestamp(-30)}] [DEBUG] Memory: 480MB / 512MB",
                f"[{get_timestamp(-10)}] [WARNING] High Memory Pressure: 95% usage",
                f"[{get_timestamp()}] [CRITICAL] Memory limit reached. Kernel sending SIGKILL (Exit Code 137).",
            ],
        },
        "UPSTREAM_TIMEOUT": {
            "trace_id": trace_id(),
            "description": "Third-party API (Stripe/Payment) not responding.",
            "logs": [
                f"[{get_timestamp(-15)}] [INFO] Calling payment-api.external.com/v1/charge",
                f"[{get_timestamp(-5)}] [DEBUG] No response after 10 seconds. Retrying...",
                f"[{get_timestamp()}] [ERROR] httpx.ReadTimeout: The read operation timed out after 15.0s.",
            ],
        },
        "REDIS_CONNECTION_REFUSED": {
            "trace_id": trace_id(),
            "description": "Redis cache instance is down or firewall blocked.",
            "logs": [
                f"[{get_timestamp(-5)}] [DEBUG] Attempting to fetch user session from Redis...",
                f"[{get_timestamp()}] [ERROR] redis.exceptions.ConnectionError: "
                + "Error 111 connecting to localhost:6379. Connection refused.",
            ],
        },
        "JWT_EXPIRED": {
            "trace_id": trace_id(),
            "description": "Client sending expired authentication tokens.",
            "logs": [
                f"[{get_timestamp(-2)}] [INFO] POST /api/checkout",
                f"[{get_timestamp()}] [ERROR] Authlib: JWTExpired: Signature has expired at {get_timestamp()}",
            ],
        },
        "DISK_FULL": {
            "trace_id": trace_id(),
            "description": "Ephemeral storage exhausted on Cloud Run instance.",
            "logs": [
                f"[{get_timestamp(-10)}] [INFO] Writing temporary PDF report to /tmp",
                f"[{get_timestamp()}] [ERROR] OSError: [Errno 28] No space left on device",
            ],
        },
        "DNS_RESOLUTION_FAILURE": {
            "trace_id": trace_id(),
            "description": "Internal microservice name not resolvable via DNS.",
            "logs": [
                f"[{get_timestamp(-5)}] [INFO] Resolving address for 'shipping-service-internal'",
                f"[{get_timestamp()}] [ERROR] socket.gaierror: [Errno -2] Name or service not known",
            ],
        },
        "RATE_LIMIT_EXCEEDED": {
            "trace_id": trace_id(),
            "description": "API Gateway 429 status from upstream provider.",
            "logs": [
                f"[{get_timestamp(-2)}] [DEBUG] Dispatching notification to Twilio",
                f"[{get_timestamp()}] [ERROR] HTTP 429: Too Many Requests. Retry-After: 3600s",
            ],
        },
        "PYTHON_RECURSION_ERROR": {
            "trace_id": trace_id(),
            "description": "Infinite loop in application logic.",
            "logs": [
                f"[{get_timestamp(-2)}] [INFO] Processing tree-structure for node 105",
                f"[{get_timestamp()}] [CRITICAL] RecursionError: maximum recursion depth exceeded in comparison",
            ],
        },
    }


def fetch_trace_logs(trace_id: str) -> str:
    if settings.MOCKTRACES and os.path.exists(settings.LOG_FILE_PATH):
        found_logs = []
        capture = False

        with open(settings.LOG_FILE_PATH) as f:
            for line in f:
                if f"TRACE: {trace_id}" in line:
                    capture = True
                    continue

                if capture:
                    if line.strip() == "":
                        break
                    found_logs.append(line.strip())

        if not found_logs:
            return f"No logs found in local file for trace_id: {trace_id}"

        return "\n".join(found_logs)

    client: Client = logging_v2.Client(project=settings.PROJECT_ID)
    log_filter = f'trace:"{trace_id}"'

    try:
        entries = client.list_entries(filter_=log_filter, order_by=logging_v2.DESCENDING, page_size=50)

        results = []
        for entry in entries:
            timestamp = entry.timestamp.strftime("%H:%M:%S")
            payload = ""

            if entry.text_payload:
                payload = entry.text_payload
            elif entry.json_payload:
                payload = entry.json_payload.get("message", str(entry.json_payload))

            results.append(f"[{timestamp}] [{entry.severity}] {payload}")
        if not results:
            return f"Search complete. No logs found for trace_id: {trace_id}"
        return "\n".join(reversed(results))

    except Exception as e:
        return f"Error connecting to Cloud Logging: {str(e)}"
