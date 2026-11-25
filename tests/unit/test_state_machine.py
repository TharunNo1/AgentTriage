import pytest

from app.domain.models import ActionType, IncidentStatus, ProposedAction, RejectionReason, Severity, Tier, TriageResult
from app.domain.state_machine import (
    InvalidTransitionError,
    can_transition,
    ensure_transition,
    next_status_after_rejection,
    next_status_after_triage,
)

S = IncidentStatus
ACTION = ProposedAction(type=ActionType.RESTART_DEPLOYMENT, params={"deployment": "api"}, rationale="r")


def _result(tier: Tier, action: ProposedAction | None = ACTION) -> TriageResult:
    return TriageResult(tier=tier, severity=Severity.HIGH, error_class="X", rca_summary="s", proposed_action=action)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.NEW, S.TRIAGING),
        (S.TRIAGING, S.REMEDIATING),
        (S.TRIAGING, S.AWAITING_APPROVAL),
        (S.AWAITING_APPROVAL, S.SUPPRESSED),
        (S.AWAITING_APPROVAL, S.MANUAL),
        (S.AWAITING_APPROVAL, S.TRIAGING),
        (S.AWAITING_APPROVAL, S.ESCALATED),
        (S.REMEDIATING, S.VERIFYING),
        (S.VERIFYING, S.RESOLVED),
        (S.VERIFYING, S.ESCALATED),
    ],
)
def test_allowed_system_transitions(current: IncidentStatus, target: IncidentStatus) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [(S.NEW, S.RESOLVED), (S.TRIAGING, S.RESOLVED), (S.RESOLVED, S.TRIAGING), (S.REMEDIATING, S.AWAITING_APPROVAL)],
)
def test_disallowed_system_transitions(current: IncidentStatus, target: IncidentStatus) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidTransitionError):
        ensure_transition(current, target)


def test_operator_can_close_any_open_incident() -> None:
    for status in (S.NEW, S.TRIAGING, S.AWAITING_APPROVAL, S.REMEDIATING, S.VERIFYING, S.ESCALATED, S.MANUAL):
        assert can_transition(status, S.RESOLVED, by_operator=True)
        assert can_transition(status, S.SUPPRESSED, by_operator=True)


def test_operator_cannot_reopen_terminal_incident() -> None:
    assert not can_transition(S.RESOLVED, S.MANUAL, by_operator=True)
    assert not can_transition(S.SUPPRESSED, S.RESOLVED, by_operator=True)


def test_operator_cannot_force_automation_states() -> None:
    assert not can_transition(S.ESCALATED, S.REMEDIATING, by_operator=True)


@pytest.mark.parametrize(
    ("result", "mode", "expected"),
    [
        (_result(Tier.AUTO_REMEDIATE), "dry_run", S.REMEDIATING),
        (_result(Tier.AUTO_REMEDIATE), "disabled", S.ESCALATED),
        (_result(Tier.APPROVAL_REQUIRED), "dry_run", S.AWAITING_APPROVAL),
        (_result(Tier.ESCALATE), "dry_run", S.ESCALATED),
        (_result(Tier.AUTO_REMEDIATE, action=None), "dry_run", S.ESCALATED),
    ],
)
def test_next_status_after_triage(result: TriageResult, mode: str, expected: IncidentStatus) -> None:
    assert next_status_after_triage(result, remediation_mode=mode) == expected  # type: ignore[arg-type]


def test_rejection_routing() -> None:
    assert next_status_after_rejection(RejectionReason.FALSE_POSITIVE, reproposals=0, max_reproposals=1) == S.SUPPRESSED
    assert next_status_after_rejection(RejectionReason.HANDLE_MANUALLY, reproposals=0, max_reproposals=1) == S.MANUAL
    assert next_status_after_rejection(RejectionReason.WRONG_ACTION, reproposals=0, max_reproposals=1) == S.TRIAGING
    assert next_status_after_rejection(RejectionReason.WRONG_ACTION, reproposals=1, max_reproposals=1) == S.MANUAL
