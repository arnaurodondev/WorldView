"""Anthropic extraction adapter — structured extraction via Claude API."""

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

_DEFAULT_MODEL_ID = "claude-sonnet-4-6"


class AnthropicExtractionAdapter:
    """Implements ExtractionClient via Anthropic API. Default model: claude-sonnet-4-6."""

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
            import anthropic
        except ImportError as exc:
            raise FatalError("anthropic package not installed; install ml-clients[anthropic]") from exc

        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        try:
            async with self._semaphore:
                try:
                    client = anthropic.AsyncAnthropic(api_key=self._api_key)
                    response = await client.messages.create(
                        model=self._model_id,
                        max_tokens=4096,
                        messages=[
                            {
                                "role": "user",
                                "content": f"{inp.prompt}\n\nContext:\n{inp.context}",
                            }
                        ],
                    )
                    # Capture actual token usage from API response
                    tokens_in = response.usage.input_tokens or 0
                    tokens_out = response.usage.output_tokens or 0
                    raw_response: str = response.content[0].text
                    logger.info("anthropic_extraction_completed", model_id=self._model_id)
                    try:
                        result: dict[str, object] = json.loads(raw_response)
                    except json.JSONDecodeError as exc:
                        raise FatalError(f"malformed extraction output: {exc}") from exc
                    return ExtractionOutput(
                        result=result,
                        raw_response=raw_response,
                        model_id=self._model_id,
                    )
                except anthropic.RateLimitError as exc:
                    raise RetryableError(f"Anthropic rate limit: {exc}") from exc
                except anthropic.APIConnectionError as exc:
                    raise RetryableError(f"Anthropic connection error: {exc}") from exc
                except anthropic.BadRequestError as exc:
                    raise FatalError(f"Anthropic bad request: {exc}") from exc
                except (RetryableError, FatalError):
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected Anthropic error: {exc}") from exc
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
                # Anthropic claude-sonnet-4-6: $0.000003 per input token, $0.000015 per output token
                cost = (tokens_in * 0.000003) + (tokens_out * 0.000015)
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
