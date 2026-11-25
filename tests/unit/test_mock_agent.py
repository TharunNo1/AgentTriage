import uuid

import pytest

from app.domain.models import ActionType, Tier
from app.domain.ports import TriageContext
from app.integrations.mock import MockTriageAgent


def _ctx(message: str, **labels: str) -> TriageContext:
    return TriageContext(
        incident_id=uuid.uuid4(), service="checkout", title="alert", messages=[message], trace_ids=[], labels=labels
    )


@pytest.mark.parametrize(
    ("message", "error_class", "tier", "action"),
    [
        ("container OOMKilled exit code 137", "OOMKilled", Tier.AUTO_REMEDIATE, ActionType.RESTART_DEPLOYMENT),
        ("The node was low on resource: memory. Pod evicted", "PodEvicted", Tier.AUTO_REMEDIATE, ActionType.DELETE_POD),
        ("upstream returned 504 Gateway Timeout", "UpstreamTimeout", Tier.AUTO_REMEDIATE, ActionType.RESTART_DEPLOYMENT),
        ("deployment exceeded its progress deadline", "StuckRollout", Tier.AUTO_REMEDIATE, ActionType.ROLLBACK_DEPLOYMENT),
        ("FATAL: too many connections for role app", "DBPoolExhausted", Tier.APPROVAL_REQUIRED, ActionType.SCALE_DEPLOYMENT),
        ("caller does not have storage.objects.get access", "IAMDenied", Tier.APPROVAL_REQUIRED, ActionType.RESTART_DEPLOYMENT),
        ("ConfigMap checkout-config key missing", "ConfigMismatch", Tier.APPROVAL_REQUIRED, ActionType.RESTART_DEPLOYMENT),
        ("row checksum failed: data corrupted", "DataIntegrity", Tier.ESCALATE, None),
        ("something nobody has seen before", "Unknown", Tier.ESCALATE, None),
    ],
)
async def test_classification(message: str, error_class: str, tier: Tier, action: ActionType | None) -> None:
    result, stats = await MockTriageAgent().triage(_ctx(message))
    assert result.error_class == error_class
    assert result.tier == tier
    assert (result.proposed_action.type if result.proposed_action else None) == action
    assert stats.agent == "mock"


async def test_action_targets_come_from_labels() -> None:
    result, _ = await MockTriageAgent().triage(_ctx("OOMKilled", namespace="shop", deployment="checkout-v2"))
    assert result.proposed_action is not None
    assert result.proposed_action.params == {"namespace": "shop", "deployment": "checkout-v2"}
