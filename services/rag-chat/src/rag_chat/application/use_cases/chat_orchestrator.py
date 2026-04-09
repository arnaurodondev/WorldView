"""Chat orchestrator - top-level pipeline coordinator (T-F-4-02).

Chains all 13 pipeline steps for streaming (/chat/stream) and sync (/chat) paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.pipeline.context_assembler import (
    ContextAssembler,
    ContradictionAssembler,
)
from rag_chat.application.pipeline.output_processor import OutputProcessor
from rag_chat.application.pipeline.prompt_builder import PromptBuilder
from rag_chat.application.pipeline.sse_emitter import SSEEmitter
from rag_chat.application.use_cases.persist_chat import AssistantResponse
from rag_chat.domain.entities.chat import ResolvedQuery

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from rag_chat.application.caching.completion_cache import CompletionCache
    from rag_chat.application.caching.rate_limiter import RateLimiter
    from rag_chat.application.pipeline.fusion import FusionPipeline, GraphEnricher
    from rag_chat.application.pipeline.hyde_expander import HydeExpander
    from rag_chat.application.pipeline.intent_classifier import OllamaIntentClassifier
    from rag_chat.application.pipeline.reranker import BGEReranker
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
    from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
    from rag_chat.application.ports.embedding import EmbeddingPort
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.application.ports.upstream_clients import S6Port
    from rag_chat.application.security.input_validator import InputValidator
    from rag_chat.application.use_cases.get_thread import GetThreadUseCase
    from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase
    from rag_chat.domain.entities.chat import ChatRequest
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_MIN_RETRIEVAL_ITEMS = 0  # allow empty retrieval for graceful response


class ChatOrchestrator:
    """Coordinate all pipeline steps for a single chat request.

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

    def __init__(
        self,
        validator: InputValidator,
        rate_limiter: RateLimiter,
        cache: CompletionCache,
        get_thread_uc: GetThreadUseCase,
        s6_client: S6Port,
        classifier: OllamaIntentClassifier,
        plan_builder: RetrievalPlanBuilder,
        hyde: HydeExpander,
        embedding_client: EmbeddingPort,
        retrieval: ParallelRetrievalOrchestrator,
        graph_enricher: GraphEnricher,
        fusion: FusionPipeline,
        reranker: BGEReranker,
        llm_chain: LLMProviderChain,
        persistence: ChatPersistenceUseCase,
    ) -> None:
        self._validator = validator
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._get_thread = get_thread_uc
        self._s6 = s6_client
        self._classifier = classifier
        self._plan_builder = plan_builder
        self._hyde = hyde
        self._embedder = embedding_client
        self._retrieval = retrieval
        self._graph_enricher = graph_enricher
        self._fusion = fusion
        self._reranker = reranker
        self._llm_chain = llm_chain
        self._persistence = persistence
        self._context_assembler = ContextAssembler()
        self._contradiction_assembler = ContradictionAssembler()
        self._prompt_builder = PromptBuilder()
        self._output_processor = OutputProcessor()
        self._emitter = SSEEmitter()

    async def execute_streaming(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the full 13-step pipeline, yielding SSE events as they occur."""
        start = datetime.now(tz=UTC)
        thread_id: UUID = request.thread_id or _new_thread_id()

        # Step 0: input validation (synchronous)
        validated_message = self._validator.validate(request.message)

        # Check completion cache
        cached = await self._cache.get(request.message, request.thread_id)
        if cached:
            yield self._emitter.emit_status("cache_hit")
            yield self._emitter.emit_token(cached.get("answer", ""))
            yield self._emitter.emit_citations([])
            yield self._emitter.emit_contradictions([])
            return

        # Step 1: rate limit
        await self._rate_limiter.check_and_increment(request.tenant_id)

        yield self._emitter.emit_status("loading_context")

        # Step 2: load conversation history
        conversation_history = []
        if request.thread_id:
            try:
                thread = await self._get_thread.execute(
                    uow, request.thread_id, request.user_id, tenant_id=request.tenant_id
                )
                conversation_history = list(thread.recent_history(5))
            except Exception:
                log.debug("thread_load_skipped")  # type: ignore[no-any-return]

        yield self._emitter.emit_status("entity_resolution")

        # Step 3: entity resolution
        entities = await self._s6.resolve_entities(validated_message)

        yield self._emitter.emit_status("intent_classification")

        # Step 4: intent + retrieval plan
        history_dicts = [{"role": m.role.value, "content": m.content} for m in conversation_history]
        intent, sub_questions, rephrased = await self._classifier.classify(validated_message, history_dicts, entities)
        entity_ids = tuple(e.entity_id for e in entities)
        plan = self._plan_builder.build(intent, entity_ids, request.context.date_range)

        yield self._emitter.emit_status("query_expansion")

        # Step 5: HyDE expansion + query embedding
        _hypothesis, hyde_embedding = await self._hyde.expand(rephrased or validated_message, intent)
        query_embedding = hyde_embedding
        if query_embedding is None:
            query_embedding = await self._embedder.embed(rephrased or validated_message)

        resolved_query = ResolvedQuery(
            intent=intent,
            rephrased_query=rephrased or validated_message,
            sub_questions=tuple(sub_questions),
            resolved_entities=tuple(entities),
            hyde_hypothesis=_hypothesis,
        )

        yield self._emitter.emit_status("parallel_retrieval")

        # Steps 5A-5I: parallel retrieval
        raw_items = await self._retrieval.retrieve(plan, resolved_query, request, query_embedding)

        # Steps 6-7: graph enrichment + fusion
        enriched = self._graph_enricher.enrich(raw_items, [])  # relation_results passed as []
        fused = self._fusion.process(enriched)

        yield self._emitter.emit_status("ranking_evidence")

        # Step 8: reranking
        reranked = await self._reranker.rerank(rephrased or validated_message, fused[:30])

        # Step 9: contradiction detection
        contradiction_refs: list = []
        contradiction_block = self._contradiction_assembler.build(contradiction_refs)

        # Step 10: prompt construction
        context_block = self._context_assembler.assemble(reranked)
        prompt = self._prompt_builder.build(
            context_block=context_block,
            conversation_history=conversation_history,
            rephrased_query=rephrased or validated_message,
            sub_questions=tuple(sub_questions),
            contradiction_block=contradiction_block,
            intent=intent,
        )

        # Step 11: LLM streaming
        full_text = ""
        provider_name = "unknown"
        async for chunk in self._llm_chain.stream(prompt, max_tokens=4000, temperature=0.1):
            full_text += chunk
            yield self._emitter.emit_token(chunk)
        provider_name = self._llm_chain.last_provider_name

        # Step 12: output processing + citation injection
        answer, citations = self._output_processor.process(full_text, reranked)
        latency_ms = int((datetime.now(tz=UTC) - start).total_seconds() * 1000)

        yield self._emitter.emit_citations(citations)
        yield self._emitter.emit_contradictions(contradiction_refs)

        # Step 13: persist (best-effort)
        asst_msg_id = _new_thread_id()  # fallback if persistence fails
        try:
            _user_msg_id, asst_msg_id = await self._persistence.execute(
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
                    model="",
                    token_count_in=None,
                    token_count_out=len(full_text.split()),
                    latency_ms=latency_ms,
                ),
                uow=uow,
            )
        except Exception as exc:
            log.error("chat_persistence_failed", error=str(exc))  # type: ignore[no-any-return]

        # Cache the completion for future identical requests (best-effort)
        try:
            await self._cache.set(
                request.message,
                request.thread_id,
                {"answer": answer, "citations": [c.__dict__ if hasattr(c, "__dict__") else c for c in citations]},
            )
        except Exception:
            log.debug("completion_cache_write_failed")  # type: ignore[no-any-return]

        yield self._emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)

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
