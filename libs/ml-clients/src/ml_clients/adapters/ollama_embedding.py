"""Ollama embedding adapter — bge-large-en-v1.5 (1024-dim)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.errors import FatalError, RetryableError
from ml_clients.text_budget import truncate_for_bge

if TYPE_CHECKING:
    import asyncio

    from observability.metrics import MLMetrics

logger = structlog.get_logger()


class OllamaEmbeddingAdapter:
    """Implements EmbeddingClient via Ollama REST API. Model: bge-large-en-v1.5 (1024-dim)."""

    EXPECTED_DIMENSION = 1024
    MODEL_ID = "bge-large-en-v1.5"

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

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        results: list[EmbeddingOutput] = []
        for inp in inputs:
            start = time.perf_counter()
            status = "success"
            try:
                async with self._semaphore:
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            text = f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text
                            # Truncate by ESTIMATED token count (ml_clients.text_budget) so
                            # the prefixed text stays under BGE's 512-token window.  Shared
                            # with the DeepInfra adapter + query embed endpoint so ingest and
                            # query vectors are pre-processed identically (task #4).  Replaces
                            # the old flat 1500-char cap, which under-truncated dense JSON text.
                            text = truncate_for_bge(text)
                            resp = await client.post(
                                f"{self._base_url}/api/embeddings",
                                json={
                                    "model": self._model_id,
                                    "prompt": text,
                                    # BP-121 fix: force Ollama to honour the model's
                                    # actual training context (512 for bge-large,
                                    # harmless for nomic-embed-text which supports 2048).
                                    # Without this, Ollama initialises bge-large with
                                    # n_ctx=4096 → GGML_ASSERT abort ("signal: aborted")
                                    # even when the input is short.
                                    "options": {"num_ctx": 512},
                                },
                            )
                            resp.raise_for_status()
                            embedding: list[float] = resp.json()["embedding"]
                            if len(embedding) != self.EXPECTED_DIMENSION:
                                raise FatalError(
                                    f"Unexpected embedding dimension: "
                                    f"{len(embedding)} (expected {self.EXPECTED_DIMENSION})",
                                )
                            results.append(
                                EmbeddingOutput(
                                    embedding=embedding,
                                    model_id=self._model_id,
                                    dimension=len(embedding),
                                ),
                            )
                            logger.info(
                                "embedding_generated",
                                model_id=self._model_id,
                                dimension=len(embedding),
                            )
                    except httpx.TimeoutException as exc:
                        raise RetryableError(f"Ollama embedding timeout: {exc}") from exc
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code >= 500:
                            raise RetryableError(f"Ollama 5xx: {exc}") from exc
                        raise FatalError(f"Ollama 4xx: {exc}") from exc
                    except FatalError:
                        raise
                    except RetryableError:
                        raise
                    except Exception as exc:
                        raise FatalError(f"Unexpected embedding error: {exc}") from exc
            except (RetryableError, FatalError):
                status = "error"
                raise
            finally:
                if self._metrics:
                    latency = time.perf_counter() - start
                    self._metrics.ml_api_requests_total.labels(
                        model_id=self._model_id, operation="embed", status=status
                    ).inc()
                    self._metrics.ml_api_latency_seconds.labels(model_id=self._model_id, operation="embed").observe(
                        latency
                    )
                    # Word-count approximation for token counts (Ollama local — zero cost)
                    token_count = len(inp.text.split())
                    self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(token_count)
                    # Ollama is local — no cost per token
                    self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(0.0)
        return results
