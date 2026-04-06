"""BGE reranker - Step 8 of the RAG pipeline (T-F-2-01).

Cross-encoder reranking using Ollama bge-reranker-v2-m3.
Input: up to 30 (query, candidate) pairs.
Output: top-12 by cross-encoder score.

Fallback on Ollama timeout: return items[:12] sorted by fusion_score.
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
