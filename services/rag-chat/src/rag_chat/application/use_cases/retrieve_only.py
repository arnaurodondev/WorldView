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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from rag_chat.application.pipeline.hyde_expander import HydeExpander
    from rag_chat.application.pipeline.intent_classifier import OllamaIntentClassifier
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
    from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
    from rag_chat.application.ports.embedding import EmbeddingPort
    from rag_chat.application.ports.upstream_clients import S6Port
    from rag_chat.application.security.input_validator import InputValidator
    from rag_chat.domain.entities.chat import ChatRequest, RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


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
        classifier: OllamaIntentClassifier,
        plan_builder: RetrievalPlanBuilder,
        hyde: HydeExpander,
        embedder: EmbeddingPort,
        retrieval: ParallelRetrievalOrchestrator,
    ) -> None:
        self._validator = validator
        self._s6 = s6_client
        self._classifier = classifier
        self._plan_builder = plan_builder
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
        """Resolve entities, classify intent, embed (if not provided), retrieve.

        When `query_embedding` is provided, the embedder is bypassed entirely
        (PLAN-0063 §0-bis L5 — precomputed embeddings for deterministic CI).
        Intent classification still runs because it drives the retrieval plan.
        """
        validated = self._validator.validate(request.message)

        entities = await self._s6.resolve_entities(validated)
        intent, sub_questions, rephrased = await self._classifier.classify(validated, [], entities)
        rephrased_or_validated = rephrased or validated

        entity_ids = tuple(e.entity_id for e in entities)
        plan = self._plan_builder.build(intent, entity_ids, request.context.date_range)

        # If a precomputed embedding is supplied, skip HyDE entirely (HyDE produces
        # an embedding too, so it would be wasted work). Otherwise run HyDE then
        # fall back to the raw embedder.
        if query_embedding is None:
            _hypothesis, hyde_embedding = await self._hyde.expand(rephrased_or_validated, intent)
            query_embedding = hyde_embedding
            if query_embedding is None:
                query_embedding = await self._embedder.embed(rephrased_or_validated)

        from rag_chat.domain.entities.chat import ResolvedQuery

        resolved_query = ResolvedQuery(
            intent=intent,
            rephrased_query=rephrased_or_validated,
            sub_questions=tuple(sub_questions),
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
            intent=str(intent),
            n_entities=len(entities),
            n_raw_items=len(raw_items),
            n_returned=len(ranked),
            embedding_provided=query_embedding is not None and len(query_embedding) > 0,
        )

        return RetrieveOnlyResult(
            intent=str(intent),
            candidates=ranked,
            rephrased_query=rephrased_or_validated,
        )
