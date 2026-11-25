from app.domain.models import TERMINAL_STATUSES, IncidentStatus, RejectionReason, RemediationMode, Tier, TriageResult

S = IncidentStatus

_OPERATOR_TARGETS = frozenset({S.RESOLVED, S.SUPPRESSED, S.MANUAL})

TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    S.NEW: frozenset({S.TRIAGING}),
    S.TRIAGING: frozenset({S.AWAITING_APPROVAL, S.REMEDIATING, S.ESCALATED, S.MANUAL}),
    S.AWAITING_APPROVAL: frozenset({S.REMEDIATING, S.SUPPRESSED, S.MANUAL, S.TRIAGING, S.ESCALATED}),
    S.REMEDIATING: frozenset({S.VERIFYING, S.ESCALATED}),
    S.VERIFYING: frozenset({S.RESOLVED, S.ESCALATED}),
    S.ESCALATED: frozenset(),
    S.MANUAL: frozenset(),
    S.RESOLVED: frozenset(),
    S.SUPPRESSED: frozenset(),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: IncidentStatus, target: IncidentStatus) -> None:
        super().__init__(f"Cannot transition incident from {current} to {target}")
        self.current = current
        self.target = target


def can_transition(current: IncidentStatus, target: IncidentStatus, *, by_operator: bool = False) -> bool:
    if target in TRANSITIONS[current]:
        return True
    return by_operator and current not in TERMINAL_STATUSES and target in _OPERATOR_TARGETS and target != current


def ensure_transition(current: IncidentStatus, target: IncidentStatus, *, by_operator: bool = False) -> None:
    if not can_transition(current, target, by_operator=by_operator):
        raise InvalidTransitionError(current, target)


def next_status_after_triage(result: TriageResult, *, remediation_mode: RemediationMode) -> IncidentStatus:
    """Decide where triage leads. The agent proposes a tier; code decides the transition.

    With remediation disabled nothing can be acted on automatically, so every incident needs a human (escalation).
    """
    if result.tier == Tier.ESCALATE or result.proposed_action is None or remediation_mode == "disabled":
        return S.ESCALATED
    if result.tier == Tier.AUTO_REMEDIATE:
        return S.REMEDIATING
    return S.AWAITING_APPROVAL


def next_status_after_rejection(reason: RejectionReason, *, reproposals: int, max_reproposals: int) -> IncidentStatus:
    match reason:
        case RejectionReason.FALSE_POSITIVE:
            return S.SUPPRESSED
        case RejectionReason.HANDLE_MANUALLY:
            return S.MANUAL
        case RejectionReason.WRONG_ACTION:
            return S.TRIAGING if reproposals < max_reproposals else S.MANUAL
