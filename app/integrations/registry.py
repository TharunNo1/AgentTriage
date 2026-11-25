from dataclasses import dataclass

from app.core.settings import Settings
from app.domain.ports import Notifier, RemediationExecutor, Ticketing, TriageAgent
from app.integrations.mock import DryRunExecutor, LoggingNotifier, MockTicketing, MockTriageAgent


@dataclass(frozen=True, slots=True)
class Integrations:
    agent: TriageAgent
    ticketing: Ticketing
    notifier: Notifier
    executor: RemediationExecutor


def build_integrations(settings: Settings) -> Integrations:
    if settings.remediation_mode == "enabled":
        raise RuntimeError("TRIAGE_REMEDIATION_MODE=enabled requires a real remediation executor, which is not available yet")
    return Integrations(
        agent=MockTriageAgent(),
        ticketing=MockTicketing(),
        notifier=LoggingNotifier(),
        executor=DryRunExecutor(),
    )
