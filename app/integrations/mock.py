"""Default adapters for local triage, simulated remediation, and offline tests."""

import hashlib
import re
from dataclasses import dataclass

from app.core.logging import get_logger
from app.domain.models import ActionType, IncidentSnapshot, ProposedAction, Severity, Tier, TriageResult
from app.domain.ports import ActionOutcome, AgentRunStats, Notification, TicketRef, TriageContext

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    error_class: str
    tier: Tier
    severity: Severity
    action: ActionType | None
    summary: str


# The first matching pattern determines the proposal when a signal mentions several failures.
_RULES: list[_Rule] = [
    _Rule(
        re.compile(r"oomkilled|out of memory|exit code 137|sigkill|memory limit", re.I),
        "OOMKilled",
        Tier.AUTO_REMEDIATE,
        Severity.HIGH,
        ActionType.RESTART_DEPLOYMENT,
        "Container exceeded its memory limit and was killed; restarting the deployment restores capacity.",
    ),
    _Rule(
        re.compile(r"evicted", re.I),
        "PodEvicted",
        Tier.AUTO_REMEDIATE,
        Severity.MEDIUM,
        ActionType.DELETE_POD,
        "Pod was evicted by the kubelet; deleting the evicted pod lets the controller reschedule it.",
    ),
    _Rule(
        re.compile(r"\b504\b|gateway timeout|deadline exceeded|upstream timeout", re.I),
        "UpstreamTimeout",
        Tier.AUTO_REMEDIATE,
        Severity.HIGH,
        ActionType.RESTART_DEPLOYMENT,
        "Requests are timing out at the gateway; restarting unhealthy replicas is the standard first response.",
    ),
    _Rule(
        re.compile(r"progress deadline|rollout.*(stuck|exceeded)|imagepullbackoff|crashloopbackoff", re.I),
        "StuckRollout",
        Tier.AUTO_REMEDIATE,
        Severity.HIGH,
        ActionType.ROLLBACK_DEPLOYMENT,
        "The latest rollout is not becoming healthy; rolling back to the previous revision.",
    ),
    _Rule(
        re.compile(r"connection pool|too many connections|pool exhausted", re.I),
        "DBPoolExhausted",
        Tier.APPROVAL_REQUIRED,
        Severity.HIGH,
        ActionType.SCALE_DEPLOYMENT,
        "Database connection pool is exhausted; scaling out spreads load but may increase DB pressure.",
    ),
    _Rule(
        re.compile(r"\b403\b|permission denied|\biam\b|forbidden|does not have .* access", re.I),
        "IAMDenied",
        Tier.APPROVAL_REQUIRED,
        Severity.MEDIUM,
        ActionType.RESTART_DEPLOYMENT,
        "Workload identity lacks a required permission; a restart only helps after the binding is fixed.",
    ),
    _Rule(
        re.compile(r"configmap|config mismatch|invalid configuration", re.I),
        "ConfigMismatch",
        Tier.APPROVAL_REQUIRED,
        Severity.MEDIUM,
        ActionType.RESTART_DEPLOYMENT,
        "Running configuration does not match the expected ConfigMap; restart to reload after review.",
    ),
    _Rule(
        re.compile(r"corrupt|schema mismatch|data loss|checksum", re.I),
        "DataIntegrity",
        Tier.ESCALATE,
        Severity.CRITICAL,
        None,
        "Possible data integrity problem; automated action is unsafe.",
    ),
]


class MockTriageAgent:
    """Keyword-rule classifier that mimics the agent contract without calling an LLM."""

    name = "mock"

    async def triage(self, ctx: TriageContext) -> tuple[TriageResult, AgentRunStats]:
        text = "\n".join([ctx.title, *ctx.messages])
        stats = AgentRunStats(agent=self.name, model="rules", prompt_version="mock-v1")
        for rule in _RULES:
            if rule.pattern.search(text):
                return self._result(rule, ctx), stats
        unknown = TriageResult(
            tier=Tier.ESCALATE,
            severity=Severity.HIGH,
            error_class="Unknown",
            rca_summary="No known failure pattern matched; escalating for human analysis.",
            evidence=ctx.messages[:3],
        )
        return unknown, stats

    @staticmethod
    def _result(rule: _Rule, ctx: TriageContext) -> TriageResult:
        action = None
        if rule.action is not None:
            params: dict[str, object] = {
                "namespace": ctx.labels.get("namespace", "default"),
                "deployment": ctx.labels.get("deployment", ctx.service),
            }
            if rule.action == ActionType.DELETE_POD:
                params["pod"] = ctx.labels.get("pod", "")
            if rule.action == ActionType.SCALE_DEPLOYMENT:
                params["replicas_delta"] = 1
            action = ProposedAction(type=rule.action, params=params, rationale=rule.summary)
        return TriageResult(
            tier=rule.tier,
            severity=rule.severity,
            error_class=rule.error_class,
            rca_summary=rule.summary,
            evidence=ctx.messages[:3],
            proposed_action=action,
        )


class MockTicketing:
    async def sync(self, incident: IncidentSnapshot, comment: str, *, allow_create: bool = True) -> TicketRef:
        ticket_id = (
            incident.ticket_id or f"MOCK-{int(hashlib.sha256(str(incident.id).encode()).hexdigest()[:6], 16) % 9000 + 1000}"
        )
        log.info("mock_ticket_synced", ticket_id=ticket_id, incident_id=str(incident.id), comment=comment)
        return TicketRef(
            ticket_id=ticket_id,
            url=incident.ticket_url or f"https://tickets.invalid/browse/{ticket_id}",
            created=incident.ticket_id is None,
        )


class LoggingNotifier:
    async def notify(self, notification: Notification) -> None:
        log.info(
            "mock_notification",
            kind=notification.kind,
            subject=notification.subject,
            severity=notification.severity,
            incident_id=str(notification.incident.id),
        )


class DryRunExecutor:
    """Records what would be executed. Real execution arrives with the Kubernetes executor (ADR 0008, Phase 3)."""

    async def execute(self, action: ProposedAction, *, dry_run: bool) -> ActionOutcome:
        if not dry_run:
            return ActionOutcome(succeeded=False, detail="No real remediation executor is configured")
        return ActionOutcome(succeeded=True, detail=f"[dry-run] would run {action.type.value} with {action.params}")
