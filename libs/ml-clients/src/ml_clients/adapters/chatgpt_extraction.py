"""ChatGPT extraction adapter — structured extraction via OpenAI API."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "gpt-5-mini"


class ChatGPTExtractionAdapter:
    """Implements ExtractionClient via OpenAI API. Default model: gpt-5-mini."""

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        *,
        semaphore: asyncio.Semaphore,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._semaphore = semaphore
        self._metrics = metrics

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        try:
            import openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        try:
            async with self._semaphore:
                try:
                    client = openai.AsyncOpenAI(api_key=self._api_key)
                    response = await client.chat.completions.create(
                        model=self._model_id,
                        messages=[
                            {"role": "system", "content": inp.prompt},
                            {"role": "user", "content": inp.context},
                        ],
                    )
                    # Capture actual token usage from API response when available
                    if response.usage is not None:
                        tokens_in = response.usage.prompt_tokens or 0
                        tokens_out = response.usage.completion_tokens or 0
                    raw_response: str = response.choices[0].message.content or ""
                    logger.info("chatgpt_extraction_completed", model_id=self._model_id)
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
                    raise RetryableError(f"OpenAI rate limit: {exc}") from exc
                except openai.APIConnectionError as exc:
                    raise RetryableError(f"OpenAI connection error: {exc}") from exc
                except openai.APIStatusError as exc:
                    if exc.status_code >= 500:
                        raise RetryableError(f"OpenAI 5xx: {exc}") from exc
                    raise FatalError(f"OpenAI 4xx: {exc}") from exc
                except (RetryableError, FatalError):
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected OpenAI error: {exc}") from exc
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(
                    model_id=self._model_id, operation="extract", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model_id, operation="extract").observe(
                    latency
                )
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(tokens_in)
                self._metrics.ml_api_tokens_out_total.labels(model_id=self._model_id).inc(tokens_out)
                # ChatGPT gpt-5-mini: $0.00000015 per input token, $0.0000006 per output token
                cost = (tokens_in * 0.00000015) + (tokens_out * 0.0000006)
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
