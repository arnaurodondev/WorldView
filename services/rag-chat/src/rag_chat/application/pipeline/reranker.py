"""RAG pipeline rerankers - Step 8 of the RAG pipeline (T-F-2-01).

Two implementations with the same ``rerank(query, items) -> items`` interface:

``CohereReranker`` (primary when ``cohere_api_key`` is set):
  - Calls Cohere Rerank API v2 (``/v2/rerank``).
  - Uses ``rerank-english-v3.0`` cross-encoder model (~300ms GPU latency).
  - Replaces ``bge-reranker-v2-m3`` which does not exist in the Ollama registry
    and causes 100% reranker failure (always falls back to fusion_score sort).

``BGEReranker`` (fallback when no Cohere key):
  - Calls Ollama ``/api/rerank`` with bge-reranker-v2-m3.
  - Falls back to items[:12] sorted by fusion_score on any error.

Both fall back gracefully to fusion_score sort so the pipeline is never blocked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_TOP_K = 12
_DEFAULT_TIMEOUT = 10.0


class BGEReranker:
    """Cross-encoder reranker backed by Ollama bge-reranker-v2-m3.

    Args:
        ollama_base_url: Base URL for the Ollama API.
        model:           Ollama reranker model (default: bge-reranker-v2-m3).
        http_client:     Optional pre-built httpx.AsyncClient (injected in tests).
        timeout:         Request timeout in seconds.
    """

    def __init__(
        self,
        ollama_base_url: str,
        model: str = "bge-reranker-v2-m3",
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._url = ollama_base_url.rstrip("/")
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._timeout = timeout

    async def rerank(self, query: str, items: list[RetrievedItem]) -> list[RetrievedItem]:
        """Re-rank *items* by cross-encoder relevance against *query*.

        Returns at most 12 items sorted by cross-encoder score DESC.
        Falls back to items[:12] sorted by fusion_score if Ollama is unreachable.
        """
        if not items:
            return []

        try:
            documents = [item.text for item in items]
            response = await self._client.post(
                f"{self._url}/api/rerank",
                json={
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            results: list[dict] = data.get("results", [])

            # results is a list of {"index": int, "relevance_score": float}
            scored: list[tuple[int, float]] = [
                (r["index"], float(r.get("relevance_score", 0.0))) for r in results if "index" in r
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            reranked = [items[idx] for idx, _ in scored[:_TOP_K] if idx < len(items)]
            log.debug(  # type: ignore[no-any-return]
                "reranker_complete",
                input_count=len(items),
                output_count=len(reranked),
            )
            return reranked

        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "reranker_fallback",
                model=self._model,
                error=str(exc),
            )
            # Fallback: top-12 by fusion_score
            fallback = sorted(items, key=lambda x: x.fusion_score, reverse=True)
            return fallback[:_TOP_K]

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── Cohere Rerank implementation ───────────────────────────────────────────────

_COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
_COHERE_DEFAULT_MODEL = "rerank-english-v3.0"
_COHERE_DEFAULT_TIMEOUT = 15.0


class CohereReranker:
    """Cross-encoder reranker backed by Cohere Rerank API v2.

    Drop-in replacement for ``BGEReranker`` with the same ``rerank()`` interface.
    Uses ``rerank-english-v3.0`` which provides excellent cross-encoder quality
    at ~300ms latency — far below the 10s+ Ollama round-trip.

    Falls back to items[:12] sorted by fusion_score if Cohere is unreachable,
    so the pipeline is never blocked by reranker unavailability.

    Args:
        api_key:     Cohere API key.
        model:       Cohere reranker model (default: rerank-english-v3.0).
        http_client: Optional pre-built httpx.AsyncClient (injected in tests).
        timeout:     Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _COHERE_DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = _COHERE_DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._timeout = timeout

    async def rerank(self, query: str, items: list[RetrievedItem]) -> list[RetrievedItem]:
        """Re-rank *items* by cross-encoder relevance against *query*.

        Returns at most 12 items sorted by cross-encoder score DESC.
        Falls back to items[:12] sorted by fusion_score if Cohere is unreachable.
        """
        if not items:
            return []

        try:
            documents = [item.text for item in items]
            response = await self._client.post(
                _COHERE_RERANK_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                    "top_n": _TOP_K,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()

            # Cohere v2 response: {"results": [{"index": int, "relevance_score": float}, ...]}
            results: list[dict] = data.get("results", [])
            scored: list[tuple[int, float]] = [
                (int(r["index"]), float(r.get("relevance_score", 0.0))) for r in results if "index" in r
            ]
            # Already sorted by Cohere (top_n), but sort defensively
            scored.sort(key=lambda x: x[1], reverse=True)
            reranked = [items[idx] for idx, _ in scored if idx < len(items)]
            log.debug(  # type: ignore[no-any-return]
                "cohere_reranker_complete",
                input_count=len(items),
                output_count=len(reranked),
            )
            return reranked

        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "cohere_reranker_fallback",
                model=self._model,
                error=str(exc),
            )
            fallback = sorted(items, key=lambda x: x.fusion_score, reverse=True)
            return fallback[:_TOP_K]

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
