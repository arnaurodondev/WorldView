"""Read-only retrieval use case for the eval harness.

PLAN-0063 W5-1 T-W5-1-00. Runs the chat pipeline up to the point ranked
candidates are produced (Steps 0/3/4/5/5A-5I) and stops — no fusion, no
reranking, no LLM, no persistence. Used by `scripts/eval_retrieval.py` to
measure retrieval quality (NDCG@10, MRR, P@5, Recall@20) over the golden set.

Why a separate use case instead of reusing ChatOrchestratorUseCase: the chat path
depends on a write UoW, persistence, rate limiter, completion cache, and the
LLM provider chain — all irrelevant for retrieval-only eval and most expensive
to set up. This use case takes only the deps strictly required to produce
ranked candidates.

Intent-free retrieval (classifier retirement):
    The vestigial pre-agent LLM intent classifier + ``RetrievalPlanBuilder``
    (``_INTENT_TO_FLAGS``) have been retired. The production chat path uses the
    agentic tool-use loop, and this eval harness was the last consumer of the
    per-intent source-selection matrix. Rather than classify intent, the harness
    now retrieves from **all** sources unconditionally. This is safe because:
      - Each retrieval branch in ``ParallelRetrievalOrchestrator`` self-gates on
        the presence of resolved entities / tickers (graph, claims, cypher,
        financial, contradictions all no-op without them), so enabling every
        flag adds no work for queries that lack the required context.
      - Every branch is wrapped in a circuit breaker and gathered with
        ``return_exceptions=True``, so empty / unavailable sources degrade
        gracefully instead of failing the retrieve.
    Retiring per-intent gating changes measured retrieval, so the committed NDCG
    baseline (``results/baseline_post_hybrid.json``) is deliberately re-captured
    alongside this change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from rag_chat.domain.entities.chat import RetrievalPlan
from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from rag_chat.application.pipeline.hyde_expander import HydeExpander
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
    from rag_chat.application.ports.embedding import EmbeddingPort
    from rag_chat.application.ports.upstream_clients import S6Port
    from rag_chat.application.security.input_validator import InputValidator
    from rag_chat.domain.entities.chat import ChatRequest, RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Intent-free retrieval plan: activate every source. Replaces the retired
# ``RetrievalPlanBuilder._INTENT_TO_FLAGS`` per-intent gating (see module
# docstring). Branch-level self-gating + circuit breakers make the extra flags
# free for queries that lack the required entity/ticker context.
_ALL_SOURCE_FLAGS: dict[str, bool] = {
    "use_chunks": True,
    "use_relations": True,
    "use_graph": True,
    "use_claims": True,
    "use_events": True,
    "use_contradictions": True,
    "use_financial": True,
    "use_portfolio": True,
    "use_cypher": True,
}

# Fixed intent used only to satisfy the HyDE expander + ResolvedQuery contracts.
# GENERAL is deliberately HyDE-INELIGIBLE (HyDE fires only for FINANCIAL_DATA /
# COMPARISON / PORTFOLIO), so the text-only path deterministically falls back to
# the plain embedder — no per-query LLM call, no non-determinism. The CI eval
# always supplies a precomputed embedding, so HyDE is skipped there regardless.
_FIXED_INTENT = QueryIntent.GENERAL

# Human-readable label surfaced in the /v1/internal/retrieve response + logs so
# it is obvious the harness no longer classifies intent.
_INTENT_LABEL = "intent_free"


@dataclass(frozen=True)
class RetrieveOnlyResult:
    """Output of RetrieveOnlyUseCase — ranked candidates + minimal metadata."""

    intent: str
    candidates: list[RetrievedItem]
    rephrased_query: str


class RetrieveOnlyUseCase:
    """Run pre-fusion retrieval and return ranked candidates."""

    def __init__(
        self,
        validator: InputValidator,
        s6_client: S6Port,
        hyde: HydeExpander,
        embedder: EmbeddingPort,
        retrieval: ParallelRetrievalOrchestrator,
    ) -> None:
        self._validator = validator
        self._s6 = s6_client
        self._hyde = hyde
        self._embedder = embedder
        self._retrieval = retrieval

    async def execute(
        self,
        request: ChatRequest,
        *,
        query_embedding: list[float] | None = None,
        top_k: int = 20,
    ) -> RetrieveOnlyResult:
        """Resolve entities, embed (if not provided), retrieve from all sources.

        Intent classification has been retired (see module docstring): the plan
        activates every source unconditionally. When ``query_embedding`` is
        provided, the embedder is bypassed entirely (PLAN-0063 §0-bis L5 —
        precomputed embeddings for deterministic CI).
        """
        validated = self._validator.validate(request.message)

        entities = await self._s6.resolve_entities(validated)

        entity_ids = tuple(e.entity_id for e in entities)
        plan = RetrievalPlan(
            **_ALL_SOURCE_FLAGS,
            entity_ids=entity_ids,
            date_filter=request.context.date_range,
        )

        # If a precomputed embedding is supplied, skip HyDE entirely (HyDE produces
        # an embedding too, so it would be wasted work). Otherwise run HyDE then
        # fall back to the raw embedder. HyDE is HyDE-ineligible for the fixed
        # GENERAL intent, so it deterministically returns (None, None) here.
        if query_embedding is None:
            _hypothesis, hyde_embedding = await self._hyde.expand(validated, _FIXED_INTENT)
            query_embedding = hyde_embedding
            if query_embedding is None:
                query_embedding = await self._embedder.embed(validated)

        from rag_chat.domain.entities.chat import ResolvedQuery

        resolved_query = ResolvedQuery(
            intent=_FIXED_INTENT,
            rephrased_query=validated,
            sub_questions=(),
            resolved_entities=tuple(entities),
            hyde_hypothesis=None,
        )

        raw_items = await self._retrieval.retrieve(plan, resolved_query, request, query_embedding)

        # Sort by score descending and truncate to top_k. The orchestrator returns
        # items aggregated across all retrieval branches with per-branch scores in
        # different units; for the eval we care about the post-aggregation rank
        # ordering, which is what the downstream fusion + rerank further refine.
        # We sort here so the eval sees a deterministic top-k.
        ranked = sorted(raw_items, key=lambda item: item.score, reverse=True)[:top_k]

        log.info(
            "retrieve_only_complete",
            intent=_INTENT_LABEL,
            n_entities=len(entities),
            n_raw_items=len(raw_items),
            n_returned=len(ranked),
            embedding_provided=query_embedding is not None and len(query_embedding) > 0,
        )

        return RetrieveOnlyResult(
            intent=_INTENT_LABEL,
            candidates=ranked,
            rephrased_query=validated,
        )
