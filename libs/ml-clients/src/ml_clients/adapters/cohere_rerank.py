"""Cohere Rerank v2 adapter — bge-reranker-v2-m3 replacement.

bge-reranker-v2-m3 is not available in the Ollama registry (ollama pull fails
with "file does not exist"), causing 100% reranker failure.  Cohere's Rerank
endpoint provides a cross-encoder model with ~300ms latency as a drop-in
replacement via a clean REST API.

Usage::

    adapter = CohereRerankAdapter(api_key="...")
    results = await adapter.rerank(query="...", documents=["doc1", "doc2"], top_n=12)
    # returns [{"index": int, "relevance_score": float}, ...]
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_RERANK_URL = "https://api.cohere.com/v2/rerank"
_DEFAULT_MODEL = "rerank-english-v3.0"


class CohereRerankAdapter:
    """Cross-encoder reranker backed by Cohere Rerank API v2.

    Args:
        api_key:  Cohere API key.
        model:    Cohere reranker model (default: rerank-english-v3.0).
        timeout:  HTTP timeout in seconds (default: 15.0).
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        *,
        timeout: float = 15.0,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._metrics = metrics

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rerank *documents* by cross-encoder relevance against *query*.

        Returns a list of ``{"index": int, "relevance_score": float}`` dicts
        sorted by ``relevance_score`` descending, length = min(top_n, len(documents)).

        Raises:
            RetryableError: 5xx or network error.
            FatalError:     4xx (auth failure, bad request).
        """
        if not documents:
            return []

        start = time.perf_counter()
        status = "success"
        try:
            payload: dict[str, Any] = {
                "model": self._model,
                "query": query,
                "documents": documents,
            }
            if top_n is not None:
                payload["top_n"] = top_n

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        _RERANK_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()

            except httpx.TimeoutException as exc:
                raise RetryableError(f"Cohere Rerank timeout: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    raise RetryableError(f"Cohere Rerank 5xx: {exc}") from exc
                raise FatalError(f"Cohere Rerank 4xx: {exc}") from exc
            except (httpx.RequestError, Exception) as exc:
                raise RetryableError(f"Cohere Rerank network error: {exc}") from exc

            results: list[dict[str, Any]] = []
            for item in data.get("results", []):
                results.append(
                    {
                        "index": int(item["index"]),
                        "relevance_score": float(item.get("relevance_score", 0.0)),
                    }
                )
            logger.debug(
                "cohere_rerank_done",
                model=self._model,
                input_count=len(documents),
                output_count=len(results),
            )
            return results
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(
                    model_id=self._model, operation="rerank", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model, operation="rerank").observe(latency)
                # Word-count approximation for token counts (query + all documents)
                token_count = len(query.split()) + sum(len(d.split()) for d in documents)
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model).inc(token_count)
                # Cohere rerank-english-v3.0: $0.002 per 1K searches = $0.000002 per call
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model).inc(0.000002)
