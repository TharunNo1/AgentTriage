import hashlib
import re

# Match whole identifiers first. Replacing digits earlier would leave fragments of timestamps and pod names.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<uuid>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b"), "<ts>"),
    (re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-[a-z0-9]{8,10}-[a-z0-9]{5}\b"), "<pod>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{8,}\b"), "<hex>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
]


def normalize_message(message: str) -> str:
    """Strip volatile tokens (ids, timestamps, numbers) so repeats of the same failure normalize identically."""
    text = message.lower()
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


def fingerprint(service: str, title: str, message: str) -> str:
    """Group signals across sources by service, title, and normalized message."""
    key = "|".join((service.strip().lower(), title.strip().lower(), normalize_message(message)))
    return hashlib.sha256(key.encode()).hexdigest()
