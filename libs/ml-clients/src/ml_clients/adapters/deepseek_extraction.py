"""DeepSeek extraction adapter — structured extraction via DeepSeek-compatible OpenAI endpoint."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "DeepSeek R1 Distill 32B"
_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekExtractionAdapter:
    """Implements ExtractionClient via DeepSeek API (OpenAI-compatible). Default model: DeepSeek R1 Distill 32B."""

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url
        self._semaphore = semaphore

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        try:
            import openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        async with self._semaphore:
            try:
                client = openai.AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
                response = await client.chat.completions.create(
                    model=self._model_id,
                    messages=[
                        {"role": "system", "content": inp.prompt},
                        {"role": "user", "content": inp.context},
                    ],
                )
                raw_response: str = response.choices[0].message.content or ""
                logger.info("deepseek_extraction_completed", model_id=self._model_id)
                try:
                    result: dict[str, object] = json.loads(raw_response)
                except json.JSONDecodeError as exc:
                    raise FatalError(f"malformed extraction output: {exc}") from exc
                return ExtractionOutput(
                    result=result,
                    raw_response=raw_response,
                    model_id=self._model_id,
                )
            except openai.RateLimitError as exc:
                raise RetryableError(f"DeepSeek rate limit (429): {exc}") from exc
            except openai.APIConnectionError as exc:
                raise RetryableError(f"DeepSeek connection error: {exc}") from exc
            except openai.APITimeoutError as exc:
                raise RetryableError(f"DeepSeek timeout: {exc}") from exc
            except openai.APIStatusError as exc:
                if exc.status_code >= 500:
                    raise RetryableError(f"DeepSeek 5xx: {exc}") from exc
                raise FatalError(f"DeepSeek 4xx: {exc}") from exc
            except (RetryableError, FatalError):
                raise
            except Exception as exc:
                raise FatalError(f"Unexpected DeepSeek error: {exc}") from exc
