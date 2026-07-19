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
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.errors import (
    FatalError,
    ProviderBillingError,
    RateLimitError,
    RetryableError,
    is_billing_status,
    is_transient_status,
    parse_retry_after,
)
from ml_clients.pricing import compute_cost, provider_cost_to_decimal
from ml_clients.text_budget import truncate_for_bge

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MODEL_ID = "BAAI/bge-large-en-v1.5"
_EXPECTED_DIMENSION = 1024

# BGE-large is a BERT encoder with a HARD 512-token context window.  Truncation is
# now driven by an ESTIMATED token count (ml_clients.text_budget) rather than a flat
# char cap: the old 1500-char limit assumed ~3 chars/token, which is wrong for the
# dense financial/JSON text this pipeline embeds (chunk-0 envelopes pack >512 tokens
# into <1500 chars → DeepInfra HTTP 400 "513 > 512", which the retry worker can never
# drain — task #4 / 2026-06-16 embedding-backlog audit).  truncate_for_bge keeps the
# input under MAX_TOKENS (480, safe headroom below 512) and is shared with the Ollama
# adapter and the query-side embed endpoint so ingest and query vectors match exactly.


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

        Applies the same instruction-prefix + token-budget truncation
        (``truncate_for_bge``) as OllamaEmbeddingAdapter and the query-side
        ``/api/v1/embed`` endpoint, so ingestion and query embeddings land in
        the same semantic space.

        Raises:
            RateLimitError:      HTTP 429 — retry honouring Retry-After.
            ProviderBillingError: HTTP 401/402/403 (spend-cap / auth refusal) —
                retryable, self-heals when the operator raises the cap.
            RetryableError:      5xx / 408 / 409 / 425 or network error — safe to retry.
            FatalError:          other 4xx (bad input), unexpected dimension, or
                malformed response — never succeeds on retry.
        """
        if not inputs:
            return []

        start = time.perf_counter()
        status = "success"
        # PLAN-0117 FR-1: verbatim DeepInfra ``usage.estimated_cost`` when the
        # /embeddings response reports it. Function-scoped (set after parsing,
        # read in the finally block) and guarded so the error path — where
        # ``data`` was never assigned — cannot NameError.
        provider_cost_usd: Decimal | None = None
        try:
            # Build text list: apply instruction prefix, THEN truncate by token budget.
            # Truncation runs on the prefixed text (the prefix tokens count toward the
            # 512-token window too), so the request can never exceed BGE's context.
            texts: list[str] = []
            for inp in inputs:
                text = f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text
                texts.append(truncate_for_bge(text))

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
                    # PLAN-0117 FR-1: capture the provider-reported cost verbatim
                    # (best-effort — the /embeddings endpoint may omit ``usage``,
                    # in which case we fall back to the price matrix below).
                    usage_obj = data.get("usage") if isinstance(data, dict) else None
                    if isinstance(usage_obj, dict):
                        provider_cost_usd = provider_cost_to_decimal(usage_obj.get("estimated_cost"))

            except httpx.TimeoutException as exc:
                raise RetryableError(f"DeepInfra embedding timeout: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                # 429 (rate-limited) is RETRYABLE — surface RateLimitError so the
                # Kafka consumer/back-off layer can honour Retry-After (LIB-005).
                if status_code == 429:
                    retry_after = parse_retry_after(exc.response.headers)
                    raise RateLimitError(
                        f"DeepInfra embedding rate-limited (429): {exc}",
                        retry_after=retry_after,
                    ) from exc
                # Spend-cap / auth refusal (401/402/403) is RETRYABLE but must NOT
                # be treated as terminal (the 2026-07-18 incident: HTTP 402 on a hit
                # spend cap abandoned 2,383 embeddings). ProviderBillingError lets the
                # retry worker re-attempt without burning its budget, so the queue
                # self-heals the moment the operator raises the cap.
                if is_billing_status(status_code):
                    raise ProviderBillingError(
                        f"DeepInfra embedding billing/auth refusal (HTTP {status_code}): {exc}"
                    ) from exc
                # 5xx / 408 / 409 / 425 — a normal bounded-retry transient failure.
                if is_transient_status(status_code):
                    raise RetryableError(f"DeepInfra embedding transient HTTP {status_code}: {exc}") from exc
                # Genuine bad request (400/404/413/422/…) — can never succeed on
                # retry (e.g. the 513>512 token overflow), so drop it as fatal.
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
                # PLAN-0117 FR-1: prefer the provider-reported cost; else fall back
                # to the canonical price matrix (``BAAI/bge-large-en-v1.5`` is priced
                # at $0.010/1M input tokens) instead of the old ad-hoc per-token
                # literal — single source of truth (FR-4a).
                if provider_cost_usd is not None:
                    cost = float(provider_cost_usd)
                else:
                    cost = float(compute_cost(self._model_id, token_count, 0))
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
