"""Chat orchestrator use case - top-level pipeline coordinator (T-F-4-02).

Delegates all 13 pipeline steps to ChatPipeline (PLAN-0077 Wave C).
The class is named ChatOrchestratorUseCase for consistency with other use cases in this layer.
"""

from __future__ import annotations

import json
from collections import Counter as _Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_cache_hits,
    rag_latency,
    rag_queries_total,
    record_reranker_position_change,
)
from rag_chat.application.use_cases.persist_chat import AssistantResponse
from rag_chat.domain.entities.chat import ResolvedQuery

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from rag_chat.application.pipeline.chat_pipeline import ChatPipeline
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.chat import ChatRequest

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _resolve_model_id(llm_chain: Any, provider_name: str) -> str:
    """Extract model_id from the active provider in the chain (Bug 4 Fix pattern).

    The LLMProviderChain sets last_provider_name but the provider object itself holds
    the model_id attribute. We retrieve it via the private provider list to avoid
    adding a new public API on LLMProviderChain.
    """
    for _p in llm_chain._providers:
        if getattr(_p, "name", None) == provider_name:
            return getattr(_p, "model_id", None) or getattr(_p, "model", None) or getattr(_p, "_model", None) or ""
    return ""


class ChatOrchestratorUseCase:
    """Coordinate all pipeline steps for a single chat request.

    After PLAN-0077 Wave C this class is a pure delegator: it holds a
    ChatPipeline and calls its step methods in order, emitting SSE events
    via pipeline.emitter between steps.  All logic lives in ChatPipeline.

    Steps (PRD §6.7):
     0. Input validation
     1. Completion cache check
     2. Rate limit enforcement
     3. Thread / conversation history load
     4. Entity resolution (S6)
     5. Intent classification + retrieval plan
     6. HyDE expansion + query embedding
     7. Parallel retrieval (Steps 5A-5I)
     8. Graph enrichment + fusion (Steps 6-7)
     9. Reranking (Step 8)
    10. Contradiction detection + prompt construction (Steps 9-10)
    11. LLM streaming (Step 11)
    12. Output processing + citation injection (Step 12)
    13. Persistence + finalize (Step 13)
    """

    def __init__(self, pipeline: ChatPipeline) -> None:
        self._pipeline = pipeline

    async def execute_streaming(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the full 13-step pipeline, yielding SSE events as they occur."""
        start = datetime.now(tz=UTC)
        thread_id: UUID = request.thread_id or _new_thread_id()
        p = self._pipeline  # shorthand

        # Step 0: input validation (raises on injection — counter incremented inside step)
        validated_message = await p.validate_input(request.message)

        # Step 1: completion cache check
        cached = await p.check_cache(request.message, request.thread_id)
        if cached:
            rag_cache_hits.labels(cache_type="completion").inc()
            yield p.emitter.emit_status("cache_hit")
            yield p.emitter.emit_token(cached.get("answer", ""))
            yield p.emitter.emit_citations([])
            yield p.emitter.emit_contradictions([])
            return

        # Step 2: rate limit
        await p.check_rate_limit(request.tenant_id)

        yield p.emitter.emit_status("loading_context")

        # Step 3: conversation history
        conversation_history = await p.load_history(request.thread_id, request.user_id, request.tenant_id, uow)

        yield p.emitter.emit_status("entity_resolution")

        # Step 4: entity resolution
        entities = await p.resolve_entities(validated_message)

        yield p.emitter.emit_status("intent_classification")

        # Step 5: intent + retrieval plan
        intent, sub_questions, rephrased, plan = await p.classify_and_plan(
            validated_message, conversation_history, entities, request.context.date_range
        )
        effective_query = rephrased or validated_message

        yield p.emitter.emit_status("query_expansion")

        # Step 5bis: HyDE expansion + query embedding
        _hypothesis, hyde_embedding = await p.expand_query(effective_query, intent)
        query_embedding = hyde_embedding
        if query_embedding is None:
            query_embedding = await p.embed_query(effective_query)

        resolved_query = ResolvedQuery(
            intent=intent,
            rephrased_query=effective_query,
            sub_questions=tuple(sub_questions),
            resolved_entities=tuple(entities),
            hyde_hypothesis=_hypothesis,
        )

        yield p.emitter.emit_status("parallel_retrieval")

        # Steps 5A-5I: parallel retrieval (metric emitted inside step)
        raw_items = await p.retrieve(plan, resolved_query, request, query_embedding)
        _type_counts = _Counter(item.item_type.value for item in raw_items)

        # Steps 6-7: graph enrichment + fusion
        fused = p.enrich_and_fuse(raw_items)

        yield p.emitter.emit_status("ranking_evidence")

        # Step 8: reranking
        reranked = await p.rerank_items(effective_query, fused)
        if fused and reranked:
            record_reranker_position_change(fused[0].item_id != reranked[0].item_id)

        # Steps 9-10: contradiction + context + prompt
        prompt, contradiction_refs, _context_block = p.build_prompt(
            reranked, conversation_history, effective_query, tuple(sub_questions), intent, _type_counts
        )

        # Step 11: LLM streaming with <think> filter
        full_text = ""
        provider_name = "unknown"
        async for filtered, raw in p.stream_llm(prompt):
            full_text += raw
            if filtered:
                yield p.emitter.emit_token(filtered)
        provider_name = p.llm_chain.last_provider_name

        # Step 12: output processing + citation injection
        answer, citations = p.process_output(full_text, reranked)
        latency_ms = int((datetime.now(tz=UTC) - start).total_seconds() * 1000)

        yield p.emitter.emit_citations(citations)
        yield p.emitter.emit_contradictions(contradiction_refs)

        # Resolve model ID from the provider chain (Bug 4 Fix pattern preserved)
        _model_id = _resolve_model_id(p.llm_chain, provider_name)
        token_count_in_est = len(prompt) // 4

        # Step 13: persist (best-effort — persist_chat swallows exceptions internally)
        asst_msg_id = _new_thread_id()
        _user_msg_id, asst_msg_id = await p.persist_chat(
            thread_id=thread_id,
            user_message=request.message,
            assistant_response=AssistantResponse(
                content=answer,
                intent=intent,
                resolved_entities=tuple(entities),
                retrieval_plan=plan,
                citations=tuple(citations),
                contradiction_refs=tuple(contradiction_refs),
                provider=provider_name,
                model=_model_id,
                token_count_in=token_count_in_est,
                token_count_out=len(full_text.split()),
                latency_ms=latency_ms,
            ),
            uow=uow,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
        )

        # Cache write (best-effort)
        await p.write_completion_cache(request.message, request.thread_id, answer, citations)

        # Record query + latency metrics
        _total_latency_s = (datetime.now(tz=UTC) - start).total_seconds()
        rag_queries_total.labels(
            intent=intent.value,
            provider=provider_name,
            tenant_id=str(request.tenant_id),
        ).inc()
        rag_latency.labels(intent=intent.value, step="total").observe(_total_latency_s)

        yield p.emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)

        # Terminal event: signals to the frontend EventSource that the stream is fully
        # complete.  Without this, some reverse-proxy setups (nginx, S9 proxy) buffer
        # the final metadata frame and the UI spinner never stops.
        yield p.emitter.emit_done()

    async def execute_sync(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> dict:
        """Run the full pipeline synchronously — collects all SSE events and returns final answer."""
        answer = ""
        citations: list = []
        contradictions: list = []
        metadata: dict = {}

        async for event in self.execute_streaming(request, uow):
            event_type = event.get("event", "")
            data = json.loads(event.get("data", "{}"))
            if event_type == "token":
                answer += data.get("text", "")
            elif event_type == "citations":
                citations = data
            elif event_type == "contradictions":
                contradictions = data
            elif event_type == "metadata":
                metadata = data

        # Bug 1 Fix A — sync path safety net: strip any residual <think> blocks from the
        # accumulated token stream. The SSE path uses _ThinkBlockFilter but regex is applied
        # here too in case a think block boundary was not caught by the real-time filter.
        answer = self._pipeline.process_output(answer, [])[0]

        return {
            "answer": answer,
            "citations": citations,
            "contradictions": contradictions,
            **metadata,
        }


def _new_thread_id() -> Any:
    """Generate a new UUIDv7 for thread/message IDs."""
    from common.ids import new_uuid7  # type: ignore[import-untyped]

    return new_uuid7()
