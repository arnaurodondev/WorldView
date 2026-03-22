"""Gemini extraction adapter — structured extraction via Google GenAI API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "gemini-2.5-pro"

# Transient error type names from google-genai SDK
_RETRYABLE_GEMINI_ERRORS = frozenset(
    {
        "ResourceExhausted",
        "ServiceUnavailable",
        "DeadlineExceeded",
        "InternalServerError",
        "TooManyRequests",
    }
)


class GeminiExtractionAdapter:
    """Implements ExtractionClient via Google GenAI API. Default model: gemini-2.5-pro."""

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        *,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._semaphore = semaphore

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        try:
            from google import genai
        except ImportError as exc:
            raise FatalError("google-genai package not installed; install ml-clients[gemini]") from exc

        async with self._semaphore:
            try:
                client = genai.Client(api_key=self._api_key)
                prompt = f"{inp.prompt}\n\nContext:\n{inp.context}"
                response = await client.aio.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                )
                raw_response: str = response.text
                logger.info("gemini_extraction_completed", model_id=self._model_id)
                try:
                    result: dict[str, object] = json.loads(raw_response)
                except json.JSONDecodeError as exc:
                    raise FatalError(f"malformed extraction output: {exc}") from exc
                return ExtractionOutput(
                    result=result,
                    raw_response=raw_response,
                    model_id=self._model_id,
                )
            except (RetryableError, FatalError):
                raise
            except Exception as exc:
                if type(exc).__name__ in _RETRYABLE_GEMINI_ERRORS:
                    raise RetryableError(f"Gemini transient error: {exc}") from exc
                raise FatalError(f"Gemini error: {exc}") from exc
