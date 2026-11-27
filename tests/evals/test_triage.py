from uuid import UUID

import pytest
from pydantic import BaseModel

from app.agent.triage import AgentResponseError, Generation, StructuredTriageAgent
from app.domain.models import Tier
from app.domain.ports import TriageContext


class ReplayProvider:
    """Return a fixed model response to exercise the production prompt and output validation offline."""

    def __init__(self, response: str) -> None:
        self.response = response

    async def generate(self, instruction: str, evidence: str, schema: type[BaseModel]) -> Generation:
        assert "untrusted" in instruction
        assert "checkout" in evidence
        assert "error_class" in schema.model_fields
        return Generation(self.response, "replay", 42, 13)


@pytest.mark.parametrize(
    ("message", "error_class"),
    [("Container terminated: OOMKilled", "OOMKilled"), ("FATAL: too many connections", "DBConnections")],
)
async def test_replays_structured_classification(message: str, error_class: str) -> None:
    provider = ReplayProvider(
        '{"severity":"high","error_class":"' + error_class + '","rca_summary":"Resource exhaustion","evidence":[]}'
    )
    context = TriageContext(UUID(int=1), "checkout", "Resource alert", [message], [])
    result, stats = await StructuredTriageAgent(provider).triage(context)

    assert result.error_class == error_class
    assert result.tier == Tier.ESCALATE
    assert result.proposed_action is None
    assert (stats.model, stats.prompt_version, stats.input_tokens, stats.output_tokens) == ("replay", "triage-v1", 42, 13)


@pytest.mark.parametrize(
    "response",
    [
        "sensitive raw text",
        '{"severity":"high","error_class":"Unknown","rca_summary":"Uncertain","evidence":[],"proposed_action":"restart"}',
    ],
)
async def test_rejects_invalid_output_without_echoing_provider_content(response: str) -> None:
    context = TriageContext(UUID(int=1), "checkout", "Alert", [], [])
    with pytest.raises(AgentResponseError, match="invalid structured output") as raised:
        await StructuredTriageAgent(ReplayProvider(response)).triage(context)
    assert response not in repr(raised.value)
