"""Ollama extraction adapter — structured JSON extraction via chat endpoint."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

    from observability.metrics import MLMetrics

logger = structlog.get_logger()


class OllamaExtractionAdapter:
    """Implements ExtractionClient via Ollama REST API (chat endpoint)."""

    def __init__(
        self,
        base_url: str,
        model_id: str,
        semaphore: asyncio.Semaphore,
        *,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._semaphore = semaphore
        self._metrics = metrics

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        start = time.perf_counter()
        status = "success"
        try:
            async with self._semaphore:
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        messages = [
                            {"role": "system", "content": inp.prompt},
                            {"role": "user", "content": inp.context},
                        ]
                        resp = await client.post(
                            f"{self._base_url}/api/chat",
                            json={
                                "model": self._model_id,
                                "messages": messages,
                                "stream": False,
                            },
                        )
                        resp.raise_for_status()
                        raw_response: str = resp.json()["message"]["content"]
                        logger.info("extraction_completed", model_id=self._model_id)
                        try:
                            result: dict[str, object] = json.loads(raw_response)
                        except json.JSONDecodeError as exc:
                            raise FatalError(f"malformed extraction output: {exc}") from exc
                        return ExtractionOutput(
                            result=result,
                            raw_response=raw_response,
                            model_id=self._model_id,
                        )
                except httpx.TimeoutException as exc:
                    raise RetryableError(f"Ollama extraction timeout: {exc}") from exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500:
                        raise RetryableError(f"Ollama 5xx: {exc}") from exc
                    raise FatalError(f"Ollama 4xx: {exc}") from exc
                except (RetryableError, FatalError):
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected extraction error: {exc}") from exc
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
                # Word-count approximation for token counts (Ollama local — zero cost)
                token_count = len(inp.context.split()) + len(inp.prompt.split())
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(token_count)
                # Ollama is local — no cost per token
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(0.0)
