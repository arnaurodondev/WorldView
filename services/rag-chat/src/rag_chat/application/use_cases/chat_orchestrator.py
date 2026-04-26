"""Chat orchestrator - top-level pipeline coordinator (T-F-4-02).

Chains all 13 pipeline steps for streaming (/chat/stream) and sync (/chat) paths.
"""

from __future__ import annotations

import json
from collections import Counter as _Counter
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
from rag_chat.infrastructure.metrics.prometheus import (
    rag_cache_hits,
    rag_contradiction_surfaced,
    rag_injection_blocked,
    rag_latency,
    rag_queries_total,
    rag_retrieval_items,
)

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


class _ThinkBlockFilter:
    """Real-time streaming filter that strips DeepSeek <think>/<reasoning>/<scratchpad> blocks.

    WHY NEEDED: DeepSeek R1 outputs a <think>...</think> reasoning block at the start
    of every response. This block must not be shown to users — it is internal chain-of-thought.
    We use a stateful buffer (not regex) because tokens arrive in arbitrary-length chunks
    and tag boundaries can be split across multiple chunks.
    """

    _OPEN_TAGS: frozenset[str] = frozenset({"think", "reasoning", "scratchpad"})

    def __init__(self) -> None:
        self._buf: str = ""
        self._in_block: bool = False
        self._block_tag: str = ""

    def feed(self, chunk: str) -> str:
        """Feed a streaming chunk; return the portion that should be emitted."""
        self._buf += chunk
        out = ""

        while self._buf:
            if self._in_block:
                # Suppress tokens until we find the closing tag for the active block.
                close = f"</{self._block_tag}>"
                idx = self._buf.lower().find(close)
                if idx >= 0:
                    # Found the closing tag — discard up to and including it, then exit block.
                    self._buf = self._buf[idx + len(close) :]
                    self._in_block = False
                    self._block_tag = ""
                else:
                    # Closing tag not yet fully received — keep the last (len(close)-1) chars
                    # in the buffer in case the close tag is split across this chunk boundary.
                    keep = len(close) - 1
                    if len(self._buf) > keep:
                        self._buf = self._buf[-keep:]
                    break
            else:
                buf_lower = self._buf.lower()
                # Find the earliest open tag in the buffer.
                earliest = len(self._buf)
                found_tag = ""
                for tag in self._OPEN_TAGS:
                    open_tag = f"<{tag}>"
                    idx = buf_lower.find(open_tag)
                    if 0 <= idx < earliest:
                        earliest = idx
                        found_tag = tag
                if found_tag:
                    # Emit everything before the opening tag, then enter block-suppression mode.
                    out += self._buf[:earliest]
                    self._buf = self._buf[earliest + len(f"<{found_tag}>") :]
                    self._in_block = True
                    self._block_tag = found_tag
                else:
                    # No open tag found — emit all but the last (max_tag_len - 1) chars in case
                    # an open tag is split at the current chunk boundary.
                    max_tag_len = max(len(f"<{t}>") for t in self._OPEN_TAGS)
                    safe = len(self._buf) - (max_tag_len - 1)
                    if safe > 0:
                        out += self._buf[:safe]
                        self._buf = self._buf[safe:]
                    break
        return out

    def flush(self) -> str:
        """Return any remaining buffer content after the stream ends.

        If we are still inside a think block when the stream ends, discard the
        buffer (incomplete block — never show to users).
        """
        if self._in_block:
            self._buf = ""
        result = self._buf
        self._buf = ""
        return result


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
        try:
            validated_message = self._validator.validate(request.message)
        except Exception as _exc:
            # Count injection blocks before re-raising so the route can return 400.
            from rag_chat.domain.errors import PromptInjectionError  # local import avoids cycle

            if isinstance(_exc, PromptInjectionError):
                rag_injection_blocked.inc()
            raise

        # Check completion cache
        cached = await self._cache.get(request.message, request.thread_id)
        if cached:
            rag_cache_hits.labels(cache_type="completion").inc()
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
        # Record item counts per item_type so the dashboard can show retrieval breakdown.
        _type_counts = _Counter(item.item_type.value for item in raw_items)
        for _source_type, _count in _type_counts.items():
            rag_retrieval_items.labels(source_type=_source_type).observe(_count)

        # Steps 6-7: graph enrichment + fusion
        enriched = self._graph_enricher.enrich(raw_items, [])  # relation_results passed as []
        fused = self._fusion.process(enriched)

        yield self._emitter.emit_status("ranking_evidence")

        # Step 8: reranking
        reranked = await self._reranker.rerank(rephrased or validated_message, fused[:30])

        # Step 9: contradiction detection
        contradiction_refs: list = []
        contradiction_block = self._contradiction_assembler.build(contradiction_refs)
        for _ref in contradiction_refs:
            _claim_type = getattr(_ref, "claim_type", "unknown")
            rag_contradiction_surfaced.labels(claim_type=str(_claim_type)).inc()

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

        # Step 11: LLM streaming — filter out <think> blocks in real time (Bug 1 Fix B).
        # WHY: DeepSeek R1 prepends a <think>...</think> chain-of-thought block.
        # We must suppress it from the SSE stream; _ThinkBlockFilter handles tokens
        # that arrive with tag boundaries split across chunk boundaries.
        full_text = ""
        provider_name = "unknown"
        think_filter = _ThinkBlockFilter()
        async for chunk in self._llm_chain.stream(prompt, max_tokens=4000, temperature=0.1):
            full_text += chunk
            filtered = think_filter.feed(chunk)
            if filtered:
                yield self._emitter.emit_token(filtered)
        # Flush any buffered content that didn't need holding for tag detection.
        remaining = think_filter.flush()
        if remaining:
            yield self._emitter.emit_token(remaining)
        provider_name = self._llm_chain.last_provider_name

        # Step 12: output processing + citation injection.
        # OutputProcessor.process() re-strips <think> blocks on the accumulated full_text
        # (catching anything the streaming filter may have missed) and extracts citations.
        answer, citations = self._output_processor.process(full_text, reranked)
        latency_ms = int((datetime.now(tz=UTC) - start).total_seconds() * 1000)

        yield self._emitter.emit_citations(citations)
        yield self._emitter.emit_contradictions(contradiction_refs)

        # Bug 4 Fix: retrieve model identifier from the active provider for the audit trail.
        # The LLMProviderChain sets _last_provider_name but the provider object itself holds
        # the model_id attribute. We retrieve it via the provider list to avoid a new public API.
        _model_id = ""
        for _p in self._llm_chain._providers:
            if getattr(_p, "name", None) == provider_name:
                _model_id = (
                    getattr(_p, "model_id", None) or getattr(_p, "model", None) or getattr(_p, "_model", None) or ""
                )
                break

        # Bug 4 Fix: estimate prompt token count from the built prompt text.
        # DeepInfra stream does not return token counts, so we use the industry-standard
        # 4-chars-per-token heuristic (same approach already used in provider_chain.py).
        token_count_in_est = len(prompt) // 4

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
                    model=_model_id,
                    token_count_in=token_count_in_est,
                    token_count_out=len(full_text.split()),
                    latency_ms=latency_ms,
                ),
                uow=uow,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
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

        # Record query + latency metrics after the full pipeline completes.
        _total_latency_s = (datetime.now(tz=UTC) - start).total_seconds()
        rag_queries_total.labels(
            intent=intent.value,
            provider=provider_name,
            tenant_id=str(request.tenant_id),
        ).inc()
        rag_latency.labels(intent=intent.value, step="total").observe(_total_latency_s)

        yield self._emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)

        # Terminal event: signals to the frontend EventSource that the stream is fully
        # complete.  Without this, some reverse-proxy setups (nginx, S9 proxy) buffer
        # the final metadata frame and the UI spinner never stops.
        yield self._emitter.emit_done()

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
        answer = self._output_processor.process(answer, [])[0]

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
