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


def build_integrations(
    settings: Settings,
    *,
    agent: TriageAgent | None = None,
    notifier: Notifier | None = None,
    ticketing: Ticketing | None = None,
) -> Integrations:
    """Wire supplied adapters to the workflow and reject live remediation while only the dry-run executor exists."""
    if settings.remediation_mode == "enabled":
        raise RuntimeError("TRIAGE_REMEDIATION_MODE=enabled requires a real remediation executor, which is not available yet")
    return Integrations(
        agent=agent if agent is not None else MockTriageAgent(),
        ticketing=ticketing if ticketing is not None else MockTicketing(),
        notifier=notifier if notifier is not None else LoggingNotifier(),
        executor=DryRunExecutor(),
    )
