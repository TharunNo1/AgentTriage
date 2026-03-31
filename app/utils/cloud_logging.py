from google.cloud import logging_v2
from app.config import settings


def fetch_trace_logs(trace_id: str) -> str:
    client = logging_v2.Client(project=settings.PROJECT_ID)
    log_filter = f'trace:"{trace_id}"'

    try:
        entries = client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING,
            page_size=50
        )

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