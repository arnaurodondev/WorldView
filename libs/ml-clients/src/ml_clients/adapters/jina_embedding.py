"""Jina AI embedding adapter — jina-embeddings-v3 (1024-dim).

Replaces local bge-large Ollama calls to eliminate model-swap contention.
Jina embeddings-v3 is 1024-dimensional — same as bge-large — so the
pgvector schema and existing indexes require no changes.

Latency: ~100-300ms per batch (vs 7-13s for bge-large on CPU Ollama).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_API_URL = "https://api.jina.ai/v1/embeddings"
_DEFAULT_MODEL = "jina-embeddings-v3"
_EXPECTED_DIMENSION = 1024

# Jina v3 supports task-specific embeddings.  Use "retrieval.passage" for
# document side and "retrieval.query" for query side to get better performance.
_DEFAULT_TASK = "retrieval.passage"


class JinaEmbeddingAdapter:
    """Implements EmbeddingClient via Jina AI REST API.

    Uses jina-embeddings-v3 which produces 1024-dimensional vectors — the
    same dimension as bge-large-en-v1.5, so it is a drop-in replacement for
    the pgvector schema.

    Args:
        api_key:  Jina AI API key (JINA_API_KEY or RAG_CHAT_JINA_API_KEY).
        model:    Jina model ID (default: jina-embeddings-v3).
        task:     Jina task type (default: retrieval.passage).
        timeout:  HTTP timeout in seconds (default: 30.0).
    """

    EXPECTED_DIMENSION = _EXPECTED_DIMENSION

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        task: str = _DEFAULT_TASK,
        *,
        timeout: float = 30.0,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._task = task
        self._timeout = timeout
        self._metrics = metrics

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        """Embed a batch of texts via the Jina AI API.

        Raises:
            RetryableError: 5xx or network error — safe to retry.
            FatalError:     4xx, unexpected dimension, or malformed response.
        """
        if not inputs:
            return []

        start = time.perf_counter()
        status = "success"
        try:
            texts = [f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text for inp in inputs]

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        _API_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "input": texts,
                            "dimensions": _EXPECTED_DIMENSION,
                            "task": self._task,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

            except httpx.TimeoutException as exc:
                raise RetryableError(f"Jina AI embedding timeout: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    raise RetryableError(f"Jina AI 5xx: {exc}") from exc
                raise FatalError(f"Jina AI 4xx: {exc}") from exc
            except (httpx.RequestError, Exception) as exc:
                raise RetryableError(f"Jina AI network error: {exc}") from exc

            # Parse response — sorted by "index" to match input order
            raw_items: list[dict] = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            if len(raw_items) != len(inputs):
                raise FatalError(f"Jina AI returned {len(raw_items)} embeddings for {len(inputs)} inputs")

            results: list[EmbeddingOutput] = []
            for item in raw_items:
                embedding: list[float] = item["embedding"]
                if len(embedding) != _EXPECTED_DIMENSION:
                    raise FatalError(
                        f"Unexpected embedding dimension: {len(embedding)} (expected {_EXPECTED_DIMENSION})"
                    )
                results.append(
                    EmbeddingOutput(
                        embedding=embedding,
                        model_id=self._model,
                        dimension=len(embedding),
                    )
                )
                logger.debug(
                    "jina_embedding_generated",
                    model_id=self._model,
                    dimension=len(embedding),
                )

            return results
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(model_id=self._model, operation="embed", status=status).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model, operation="embed").observe(latency)
                # Word-count approximation for token counts (Jina jina-embeddings-v3)
                token_count = sum(len(inp.text.split()) for inp in inputs)
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model).inc(token_count)
                # Jina jina-embeddings-v3: $0.02 per 1M tokens = $0.000000020 per token
                cost = token_count * 0.000000020
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model).inc(cost)
