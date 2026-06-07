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

import asyncio
from typing import TYPE_CHECKING

import httpx
import structlog

from rag_chat.application.metrics.prometheus import rag_pipeline_stage_input_size

if TYPE_CHECKING:
    from uuid import UUID

    from rag_chat.application.ports.cost_recorder import CostRecorder
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

        rag_pipeline_stage_input_size.labels(stage="reranker").observe(len(items))

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
        cost_recorder: CostRecorder | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._timeout = timeout
        # PLAN-0107 follow-up: per-call USD cost recorder. Cohere Rerank is
        # billed per search (not per token) — the pricing matrix registers
        # ``rerank-english-v3.0`` with ``per_call_usd=$0.002`` so callers
        # can pass tokens_in=1 to signal a successful billable call.
        self._cost_recorder = cost_recorder

    async def rerank(
        self,
        query: str,
        items: list[RetrievedItem],
        *,
        thread_id: UUID | None = None,
    ) -> list[RetrievedItem]:
        """Re-rank *items* by cross-encoder relevance against *query*.

        Returns at most 12 items sorted by cross-encoder score DESC.
        Falls back to items[:12] sorted by fusion_score if Cohere is unreachable.
        """
        if not items:
            return []

        rag_pipeline_stage_input_size.labels(stage="reranker").observe(len(items))

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

            # PLAN-0107 follow-up: emit per-call USD cost on success. Cohere
            # bills flat $0.002 per search via the per_call_usd field —
            # tokens_in=1 signals "successful billable call"; tokens_out=0
            # (Cohere does not return token usage and reranker output is not
            # token-billed). Done BEFORE result parsing so the cost is still
            # recorded if downstream parse logic raises.
            await self._emit_cost(thread_id=thread_id, tokens_in=1)

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

    async def _emit_cost(self, *, thread_id: UUID | None, tokens_in: int) -> None:
        """Fire-and-forget per-call cost emit. Never raises.

        WHY a helper: keeps the rerank() body readable and centralises the
        try/except defence. We use ``asyncio.create_task`` rather than
        awaiting so the rerank caller never blocks on the cost recorder's
        DB round-trip. ``tokens_in=0`` means a failed call (per-call pricing
        treats 0/0 tokens as a non-billable failure — see pricing.py).
        """
        if self._cost_recorder is None:
            return
        try:
            asyncio.create_task(  # noqa: RUF006
                self._cost_recorder.record(
                    thread_id=thread_id,
                    model_id=self._model,
                    tokens_in=tokens_in,
                    tokens_out=0,
                    call_site="reranker",
                )
            )
        except Exception as exc:  # pragma: no cover — defence in depth
            log.warning(  # type: ignore[no-any-return]
                "cohere_reranker_cost_recorder_failed",
                model=self._model,
                error=str(exc),
            )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── DeepInfra Rerank implementation ────────────────────────────────────────────

# PLAN-0052 platform-QA round 5 (2026-05-01): the canonical reranker. Project
# memory + live probe confirmed that BAAI/bge-reranker-v2-m3 is NOT available
# on our DeepInfra account. The Qwen3-Reranker family IS available via
# DeepInfra's `/v1/inference/{model}` endpoint and gives sub-second cross-
# encoder quality at $0.00025-0.000625 per query (3 docs sample). The 0.6B
# variant is the right default — fastest, cheapest, accurate enough for top-k
# rerank of news chunks. We cap input documents at MAX_DOCS so a 100-chunk
# retrieval doesn't balloon the request payload (the reranker scores all docs
# linearly; truncating to the top-N by fusion_score before sending is the
# standard pattern + saves both latency and cost).

_DEEPINFRA_RERANK_BASE = "https://api.deepinfra.com/v1/inference"
_DEEPINFRA_DEFAULT_MODEL = "Qwen/Qwen3-Reranker-0.6B"
_DEEPINFRA_DEFAULT_TIMEOUT = 10.0
# Cap the payload — even though some retrievals hand us 50+ candidates, the
# reranker only needs the top-N pre-filtered by fusion_score. 24 is roughly
# 2x the final top-k (12) so we get genuine reordering signal without paying
# for tokens we'd ignore. Empirically: cost grows ~linearly with doc count.
_DEEPINFRA_MAX_DOCS = 24


class DeepInfraReranker:
    """Cross-encoder reranker backed by DeepInfra Qwen3-Reranker.

    Drop-in replacement for ``BGEReranker`` / ``CohereReranker`` with the
    same ``rerank()`` interface. Uses the DeepInfra inference endpoint
    (NOT the OpenAI-compatible chat endpoint) which exposes a dedicated
    `{queries, documents} → {scores}` schema.

    Payload optimization:
      - Truncate `items` to MAX_DOCS (default 24) by fusion_score before
        sending — the cross-encoder only needs to refine the head.
      - Each document is `item.text` (chunk content already sliced upstream).

    Args:
        api_key:     DeepInfra API key.
        model:       Reranker model (default: ``Qwen/Qwen3-Reranker-0.6B``).
        http_client: Optional pre-built httpx.AsyncClient (injected in tests).
        timeout:     Request timeout in seconds.
        max_docs:    Cap on documents sent to the reranker (default 24).
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEEPINFRA_DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = _DEEPINFRA_DEFAULT_TIMEOUT,
        max_docs: int = _DEEPINFRA_MAX_DOCS,
        cost_recorder: "CostRecorder | None" = None,
    ) -> None:
        # cost_recorder accepted for interface symmetry with CohereReranker (PLAN-0107).
        # No per-call cost recording yet for DeepInfra rerank — rerank pricing
        # rolls up into the shared DeepInfra spend; leaving the hook present so
        # app.py wiring stays uniform across reranker implementations.
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._timeout = timeout
        self._max_docs = max_docs
        self._cost_recorder = cost_recorder

    async def rerank(self, query: str, items: list[RetrievedItem]) -> list[RetrievedItem]:
        """Re-rank *items* by cross-encoder relevance against *query*."""
        if not items:
            return []

        rag_pipeline_stage_input_size.labels(stage="reranker").observe(len(items))

        # Pre-filter to the top-N candidates by fusion_score so we don't pay
        # the reranker for chunks the caller would have dropped anyway.
        head = sorted(items, key=lambda x: x.fusion_score, reverse=True)[: self._max_docs]
        documents = [item.text for item in head]
        url = f"{_DEEPINFRA_RERANK_BASE}/{self._model}"

        try:
            response = await self._client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"queries": [query], "documents": documents},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            scores = data.get("scores") or []
            if len(scores) != len(documents):
                raise ValueError(
                    f"deepinfra_reranker score-length mismatch: got {len(scores)} for {len(documents)} docs"
                )
            scored = sorted(zip(head, scores, strict=False), key=lambda x: x[1], reverse=True)
            reranked = [item for item, _ in scored[:_TOP_K]]
            log.debug(  # type: ignore[no-any-return]
                "deepinfra_reranker_complete",
                model=self._model,
                input_count=len(items),
                head_count=len(head),
                output_count=len(reranked),
                input_tokens=data.get("input_tokens"),
            )
            return reranked

        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "deepinfra_reranker_fallback",
                model=self._model,
                error=str(exc),
            )
            fallback = sorted(items, key=lambda x: x.fusion_score, reverse=True)
            return fallback[:_TOP_K]

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
