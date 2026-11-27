import asyncio

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.agent.triage import AgentResponseError, Generation


class GeminiProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key, enterprise=False)
        self._model = model

    async def aclose(self) -> None:
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()

    async def generate(self, instruction: str, evidence: str, schema: type[BaseModel]) -> Generation:
        """Require a completed generation before passing the text to the schema validator."""
        try:
            async with asyncio.timeout(30):
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=evidence,
                    config=types.GenerateContentConfig(
                        system_instruction=instruction,
                        response_mime_type="application/json",
                        response_schema=schema,
                        max_output_tokens=2048,
                        automatic_continuation=False,
                    ),
                )
                content = response.text
        except Exception as exc:
            # Provider exceptions can contain request or response data.
            raise AgentResponseError(f"Gemini generation failed ({type(exc).__name__})") from None
        if not response.candidates or response.candidates[0].finish_reason != types.FinishReason.STOP:
            raise AgentResponseError("Gemini did not finish structured output")
        if not content:
            raise AgentResponseError("Gemini returned empty structured output")
        usage = response.usage_metadata
        return Generation(
            content,
            (response.model_version or self._model)[:128],
            (usage.prompt_token_count or 0) if usage else 0,
            (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0) if usage else 0,
        )
