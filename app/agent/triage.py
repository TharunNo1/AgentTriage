import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.models import Severity, Tier, TriageResult
from app.domain.ports import AgentRunStats, TriageContext

PROMPT_VERSION = "triage-v1"


class AgentResponseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    async def generate(self, instruction: str, evidence: str, schema: type[BaseModel]) -> Generation: ...


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    error_class: str = Field(min_length=1, max_length=100)
    rca_summary: str = Field(min_length=1, max_length=2000)
    evidence: list[Annotated[str, Field(max_length=500)]] = Field(max_length=5)


class StructuredTriageAgent:
    """Validate the provider analysis and route every result to human escalation."""

    name = "gemini"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._instruction = files("app.agent").joinpath("prompts", f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")

    async def triage(self, ctx: TriageContext) -> tuple[TriageResult, AgentRunStats]:
        # Keep alert text and operator feedback in the bounded evidence payload, separate from the versioned instruction.
        evidence = json.dumps(
            {
                "service": ctx.service[:150],
                "title": ctx.title[:500],
                "messages": [message[:1000] for message in ctx.messages[:8]],
                "operator_feedback": ctx.operator_feedback[:500] if ctx.operator_feedback else None,
            }
        )
        response = await self._provider.generate(self._instruction, evidence, Analysis)
        try:
            analysis = Analysis.model_validate_json(response.text)
        except ValidationError:
            raise AgentResponseError("Gemini returned invalid structured output") from None
        return (
            TriageResult(Tier.ESCALATE, analysis.severity, analysis.error_class, analysis.rca_summary, analysis.evidence),
            AgentRunStats(self.name, response.model, PROMPT_VERSION, response.input_tokens, response.output_tokens),
        )
