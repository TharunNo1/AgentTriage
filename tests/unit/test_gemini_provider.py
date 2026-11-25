from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from google.genai import types
from pytest import MonkeyPatch

from app.agent import gemini
from app.agent.triage import Analysis, Generation


async def test_gemini_provider_requests_bounded_structured_generation(monkeypatch: MonkeyPatch) -> None:
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(parts=[types.Part(text="{}")]),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=2, thoughts_token_count=3
        ),
    )
    generate = AsyncMock(return_value=response)
    aclose = AsyncMock()
    close = Mock()
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate), aclose=aclose), close=close)
    monkeypatch.setattr(gemini.genai, "Client", Mock(return_value=client))

    provider = gemini.GeminiProvider(api_key="test-key", model="test-model")
    assert await provider.generate("Read-only analysis", "incident evidence", Analysis) == Generation("{}", "test-model", 10, 5)
    generate.assert_awaited_once()
    assert generate.call_args.kwargs["contents"] == "incident evidence"
    config = generate.call_args.kwargs["config"]
    assert config.response_schema is Analysis
    assert config.max_output_tokens == 2048
    assert config.automatic_continuation is False
    await provider.aclose()
    aclose.assert_awaited_once()
    close.assert_called_once()
