import re

def run_remediation_task(command: str, rationale: str) -> str:
    """
    Executes or mocks a GCP/Kubernetes remediation command.

    Args:
        command: The gcloud or kubectl command to run.
        rationale: Why this command is being executed.
    """
    ALLOWED_PATTERNS = [
        r"^kubectl rollout restart deployment/.*",
        r"^kubectl scale deployment/.* --replicas=[0-9]+",
        r"^kubectl delete pod .*",
        r"^gcloud compute instances reset .*",
        r"^gcloud logging read .*"
    ]

    is_safe = any(re.match(pattern, command) for pattern in ALLOWED_PATTERNS)

    if not is_safe:
        return f"REJECTED: Command '{command}' is not in the safety whitelist."

    return (
        f"[MOCK RUN SUCCESSFUL]\n"
        f"Intent: {rationale}\n"
        f"Command: `{command}`\n"
    )

