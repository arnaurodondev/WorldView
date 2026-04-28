"""DeepInfra embedding adapter — BAAI/bge-large-en-v1.5 (1024-dim, GPU-hosted).

Drop-in replacement for OllamaEmbeddingAdapter that calls DeepInfra's
OpenAI-compatible embeddings endpoint instead of local Ollama.

Advantages over local bge-large Ollama:
  - Latency: ~50-150ms vs 7-13s on CPU Ollama
  - No Ollama model-swap contention (shared GPU pool vs single-thread CPU)
  - Same BAAI/bge-large-en-v1.5 model → identical 1024-dim output → pgvector schema unchanged
  - No GGML context-window abort risk (BP-121)

Prerequisites:
  - DeepInfra API key (same account used for extraction_api_key is fine)
  - Model hosted at api.deepinfra.com: BAAI/bge-large-en-v1.5 (1024-dim, confirmed)

Usage in nlp-pipeline consumer:
  client = DeepInfraEmbeddingAdapter(
      api_key=settings.embedding_api_key,
      model_id=settings.embedding_api_model_id,  # "BAAI/bge-large-en-v1.5"
      base_url=settings.embedding_api_base_url,  # "https://api.deepinfra.com/v1/openai"
  )
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

_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MODEL_ID = "BAAI/bge-large-en-v1.5"
_EXPECTED_DIMENSION = 1024

# BGE-large BERT context window = 512 tokens. Apply the same 1500-char truncation
# used by OllamaEmbeddingAdapter and the nlp-pipeline embed endpoint so that
# ingestion embeddings and query embeddings remain in the same semantic space.
_MAX_CHARS = 1500


class DeepInfraEmbeddingAdapter:
    """Implements EmbeddingClient via DeepInfra OpenAI-compatible embeddings API.

    Uses BAAI/bge-large-en-v1.5 (GPU-hosted on DeepInfra) which produces
    1024-dimensional vectors — identical to local bge-large Ollama — so this
    adapter is a zero-schema-change replacement for OllamaEmbeddingAdapter.

    Args:
        api_key:  DeepInfra API key (env: NLP_PIPELINE_EMBEDDING_API_KEY).
        model_id: Model to request (default: BAAI/bge-large-en-v1.5, 1024-dim).
        base_url: API base URL (default: https://api.deepinfra.com/v1/openai).
        timeout:  HTTP timeout in seconds (default: 30.0).
    """

    EXPECTED_DIMENSION = _EXPECTED_DIMENSION

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._metrics = metrics

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        """Embed a batch of texts via DeepInfra OpenAI-compatible embeddings API.

        Applies the same instruction-prefix + 1500-char truncation as
        OllamaEmbeddingAdapter so that ingestion and query embeddings land in
        the same semantic space.

        Raises:
            RetryableError: 5xx or network error — safe to retry.
            FatalError:     4xx, unexpected dimension, or malformed response.
        """
        if not inputs:
            return []

        start = time.perf_counter()
        status = "success"
        try:
            # Build text list: apply instruction prefix + truncate to 1500 chars.
            texts: list[str] = []
            for inp in inputs:
                text = f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text
                if len(text) > _MAX_CHARS:
                    text = text[:_MAX_CHARS]
                texts.append(text)

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model_id,
                            "input": texts,
                            "encoding_format": "float",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

            except httpx.TimeoutException as exc:
                raise RetryableError(f"DeepInfra embedding timeout: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    raise RetryableError(f"DeepInfra embedding 5xx: {exc}") from exc
                raise FatalError(f"DeepInfra embedding 4xx: {exc}") from exc
            except (httpx.RequestError, Exception) as exc:
                raise RetryableError(f"DeepInfra embedding network error: {exc}") from exc

            # Parse response — items are sorted by "index" to preserve input order.
            raw_items: list[dict] = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            if len(raw_items) != len(inputs):
                raise FatalError(f"DeepInfra embedding returned {len(raw_items)} results for {len(inputs)} inputs")

            results: list[EmbeddingOutput] = []
            for item in raw_items:
                embedding: list[float] = item["embedding"]
                if len(embedding) != _EXPECTED_DIMENSION:
                    raise FatalError(
                        f"Unexpected embedding dimension: {len(embedding)} (expected {_EXPECTED_DIMENSION}). "
                        f"Ensure model '{self._model_id}' produces 1024-dim vectors — "
                        f"BAAI/bge-large-en-v1.5 is confirmed 1024-dim on DeepInfra."
                    )
                results.append(
                    EmbeddingOutput(
                        embedding=embedding,
                        model_id=self._model_id,
                        dimension=len(embedding),
                    )
                )
                logger.debug(
                    "deepinfra_embedding_generated",
                    model_id=self._model_id,
                    dimension=len(embedding),
                )

            logger.info(
                "deepinfra_embedding_batch_ok",
                model_id=self._model_id,
                count=len(results),
            )
            return results
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(
                    model_id=self._model_id, operation="embed", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model_id, operation="embed").observe(latency)
                # Word-count approximation for token counts (BAAI/bge-large-en-v1.5)
                token_count = sum(len(inp.text.split()) for inp in inputs)
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(token_count)
                # DeepInfra BAAI/bge-large-en-v1.5: $0.013 per 1M tokens = $0.000000013 per token
                cost = token_count * 0.000000013
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
