"""ChatPipeline — composable pipeline value object (PLAN-0077 Wave B, T-B-1).

Encapsulates all 16 step methods as named async/sync methods.
Per-request state (validated message, history, intent, entities, etc.) is
passed as method arguments and returned as method outputs — the class itself
holds NO mutable per-request state.

_ThinkBlockFilter is defined here (moved from chat_orchestrator.py so that
Wave C can import it from one canonical location).
"""

from __future__ import annotations

import dataclasses
from collections import Counter as _Counter
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_contradiction_surfaced,
    rag_injection_blocked,
    rag_injection_blocked_layer2,
    rag_retrieval_items,
)
from rag_chat.application.pipeline.context_assembler import (
    ContextAssembler,
    ContradictionAssembler,
)
from rag_chat.application.pipeline.output_processor import OutputProcessor
from rag_chat.application.pipeline.prompt_builder import PromptBuilder
from rag_chat.application.pipeline.prompts import RetrievalCounts
from rag_chat.application.pipeline.sse_emitter import SSEEmitter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from rag_chat.application.caching.completion_cache import CompletionCache
    from rag_chat.application.caching.rate_limiter import RateLimiter
    from rag_chat.application.pipeline.hyde_expander import HydeExpander
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
    from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
    from rag_chat.application.ports.embedding import EmbeddingPort
    from rag_chat.application.ports.intent_classifier import IntentClassifierPort
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.application.ports.upstream_clients import S6Port
    from rag_chat.application.security.input_validator import InputValidator
    from rag_chat.application.security.llm_injection_classifier import LLMInjectionClassifier
    from rag_chat.application.use_cases.get_thread import GetThreadUseCase
    from rag_chat.application.use_cases.persist_chat import AssistantResponse, ChatPersistenceUseCase
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Think-block streaming filter ──────────────────────────────────────────────


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


# ── ChatPipeline value object ─────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ChatPipeline:
    """Composable pipeline value object. Holds collaborators; all state is per-call.

    Each method encapsulates exactly one named pipeline step from
    ChatOrchestratorUseCase.execute_streaming. Per-request state
    (validated message, history, intent, etc.) is passed as arguments
    and returned as the output of each method — the dataclass itself
    holds NO mutable per-request state, so it is fully re-entrant.

    Usage pattern (Wave C will wire this):
        pipeline = ChatPipeline(validator=..., rate_limiter=..., ...)
        validated = await pipeline.validate_input(request.message)
        cached = await pipeline.check_cache(validated, request.thread_id)
        ...
    """

    # ── Required collaborator fields (no defaults) ────────────────────────────
    # All are injected at construction time and must be provided by the caller.

    validator: InputValidator
    rate_limiter: RateLimiter
    cache: CompletionCache
    get_thread: GetThreadUseCase
    s6_client: S6Port
    hyde: HydeExpander
    embedder: EmbeddingPort
    # BGEReranker | DeepInfraReranker | CohereReranker — all expose .rerank()
    reranker: Any
    llm_chain: LLMProviderChain
    persistence: ChatPersistenceUseCase

    # ── Classical-path collaborators (optional after PLAN-0067 W11-3) ─────────
    # IntentClassifier, RetrievalPlanBuilder, ParallelRetrievalOrchestrator are
    # no longer used by ChatOrchestratorUseCase (tool-use path replaced them).
    # They remain here for RetrieveOnlyUseCase compatibility and are None by
    # default for the chat pipeline.  Dataclass field ordering: fields with
    # defaults must come after fields without defaults.
    # Both OllamaIntentClassifier and DeepInfraIntentClassifier satisfy IntentClassifierPort
    classifier: IntentClassifierPort | None = None  # type: ignore[assignment]
    plan_builder: RetrievalPlanBuilder | None = None  # type: ignore[assignment]
    retrieval: ParallelRetrievalOrchestrator | None = None  # type: ignore[assignment]

    # ── E-8: Layer 2 LLM semantic injection classifier (optional) ─────────────
    # When wired, runs after Layer 1 (regex + PII) passes. None → Layer 2 skipped.
    # WHY optional: allows deployments without a DeepInfra API key to still run
    # Layer 1 protection. Production deployments SHOULD set this.
    llm_classifier: LLMInjectionClassifier | None = None  # type: ignore[assignment]

    # ── Stateless helper fields (default-instantiated) ────────────────────────
    # These hold no per-request state; constructing them here avoids
    # the caller needing to pass them explicitly.

    context_assembler: ContextAssembler = dataclasses.field(default_factory=ContextAssembler)
    contradiction_assembler: ContradictionAssembler = dataclasses.field(default_factory=ContradictionAssembler)
    prompt_builder: PromptBuilder = dataclasses.field(default_factory=PromptBuilder)
    output_processor: OutputProcessor = dataclasses.field(default_factory=OutputProcessor)
    emitter: SSEEmitter = dataclasses.field(default_factory=SSEEmitter)

    # ── Step 0: Input validation ──────────────────────────────────────────────

    async def validate_input(self, message: str) -> str:
        """Step 0: Input validation — Layer 1 (regex + PII) then optional Layer 2 (LLM).

        Layer 1 (synchronous, InputValidator):
          - HTML strip → truncate → PII check → regex injection heuristics → XML-wrap
        Layer 2 (async, LLMInjectionClassifier, E-8):
          - Semantic classification via small LLM (Qwen/Qwen3.5-0.8B on DeepInfra)
          - Only runs when self.llm_classifier is wired AND Layer 1 passes
          - Fail-closed: classifier errors → block the message

        Returns the sanitised, XML-wrapped message string.

        Raises:
            PromptInjectionError: if Layer 1 heuristic or Layer 2 LLM fires
                                  (rag_injection_blocked counter incremented).
            PIIDetectedError: if PII is detected in the message.
        """
        # ── Layer 1: synchronous regex + PII ─────────────────────────────────
        try:
            # InputValidator.validate() is synchronous — no I/O occurs.
            validated = self.validator.validate(message)
        except Exception as _exc:
            # Import locally to avoid circular imports at module level.
            from rag_chat.domain.errors import PromptInjectionError

            if isinstance(_exc, PromptInjectionError):
                # Increment the blocked-injection metric BEFORE re-raising so the
                # route handler receives the exception with the metric already recorded.
                rag_injection_blocked.inc()
            raise

        # ── Layer 2: LLM semantic classifier (E-8) ───────────────────────────
        if self.llm_classifier is not None:
            # Pass the RAW (pre-XML-wrap) message to the classifier so the LLM sees
            # the actual user text, not the sanitised+wrapped version.
            is_unsafe = await self.llm_classifier.classify(message)
            if is_unsafe:
                from rag_chat.domain.errors import PromptInjectionError

                # Increment both the general blocked counter and the Layer 2 specific one.
                rag_injection_blocked.inc()
                rag_injection_blocked_layer2.inc()
                raise PromptInjectionError("Semantic injection detected")

        return validated

    # ── Step 1: Completion cache check ───────────────────────────────────────

    async def check_cache(self, message: str, thread_id: UUID | None) -> dict | None:  # type: ignore[type-arg]
        """Step 1: Check the completion cache for an identical prior request.

        Returns the cached response dict or None on a cache miss.
        The caller is responsible for emitting rag_cache_hits metric on a hit.
        """
        return await self.cache.get(message, thread_id)

    # ── Step 2: Rate limit enforcement ───────────────────────────────────────

    async def check_rate_limit(self, tenant_id: UUID) -> None:
        """Step 2: Enforce per-tenant sliding-window rate limit.

        Raises:
            RateLimitExceededError: if the tenant has exceeded the configured limit.
        """
        await self.rate_limiter.check_and_increment(tenant_id)

    # ── Step 3: Conversation history load ────────────────────────────────────

    async def load_history(
        self,
        thread_id: UUID | None,
        user_id: UUID,
        tenant_id: UUID,
        uow: RagUnitOfWorkPort,
    ) -> list:  # list[ChatMessage]
        """Step 3: Load the last 5 turns of conversation history for the thread.

        Returns an empty list when:
        - thread_id is None (new conversation, no history to load)
        - GetThreadUseCase raises any exception (graceful degradation)
        """
        if not thread_id:
            # No thread yet — new conversation, skip DB lookup.
            return []

        try:
            thread = await self.get_thread.execute(uow, thread_id, user_id, tenant_id=tenant_id)
            return list(thread.recent_history(5))
        except Exception:
            # Thread load failure must never abort the pipeline — the LLM can still
            # produce a useful response without conversation history.
            log.debug("thread_load_skipped")  # type: ignore[no-any-return]
            return []

    # ── Step 4: Entity resolution via S6 ─────────────────────────────────────

    async def resolve_entities(self, message: str) -> list:
        """Step 4: Resolve named entities from the validated message via S6.

        Returns a list of ResolvedEntity objects. May return an empty list if
        S6 finds no entities (handled gracefully downstream).
        """
        return await self.s6_client.resolve_entities(message)

    # ── Step 5: Intent classification + retrieval plan ───────────────────────

    async def classify_and_plan(
        self,
        message: str,
        history: list,
        entities: list,
        date_range: Any = None,
    ) -> tuple:  # (QueryIntent, list[str] sub_questions, str|None rephrased, RetrievalPlan)
        """Step 5: Intent classification + retrieval plan building.

        Converts history messages to dicts (role/content) before passing to
        the classifier. Returns (intent, sub_questions, rephrased, plan).
        """
        # PLAN-0067 W11-3: classifier and plan_builder are optional on ChatPipeline.
        # classify_and_plan() is only called by RetrieveOnlyUseCase (eval harness);
        # ChatOrchestratorUseCase uses the tool-use path and does not call this method.
        if self.classifier is None or self.plan_builder is None:
            raise RuntimeError("classify_and_plan() requires classifier and plan_builder (not set on this pipeline)")

        # Convert Message domain objects → plain dicts for the classifier API.
        # The classifier expects [{"role": "user"|"assistant", "content": "..."}].
        history_dicts = [{"role": m.role.value, "content": m.content} for m in history]

        intent, sub_questions, rephrased = await self.classifier.classify(message, history_dicts, entities)

        # Build entity IDs tuple for the retrieval plan.
        entity_ids = tuple(e.entity_id for e in entities)
        plan = self.plan_builder.build(intent, entity_ids, date_range)

        return intent, sub_questions, rephrased, plan

    # ── Step 5bis-a: HyDE query expansion ────────────────────────────────────

    async def expand_query(
        self,
        message: str,
        intent: Any,
    ) -> tuple:  # (str|None hypothesis, list[float]|None embedding)
        """Step 5bis-a: HyDE (Hypothetical Document Embedding) expansion.

        Returns (hypothesis_text, hypothesis_embedding) or (None, None) when:
        - intent is not in the HyDE-eligible set
        - any LLM or embedding error occurs (graceful degradation)
        """
        return await self.hyde.expand(message, intent)

    # ── Step 5bis-b: Query embedding ─────────────────────────────────────────

    async def embed_query(self, text: str) -> list:  # list[float]
        """Step 5bis-b: Embed the query text (or rephrased query).

        Used when HyDE returns (None, None) — i.e. the intent is not eligible
        for HyDE expansion, or HyDE failed gracefully.
        """
        return await self.embedder.embed(text)

    # ── Steps 5A-5I: Parallel retrieval ──────────────────────────────────────

    async def retrieve(
        self,
        plan: Any,
        resolved_query: Any,
        request: Any,
        embedding: list,
    ) -> list:
        """Steps 5A-5I: Execute parallel retrieval across all enabled sources.

        Delegates to ParallelRetrievalOrchestrator which runs all enabled
        retrieval tasks concurrently (asyncio.gather). Each task has a 5s timeout
        and returns an empty list on failure (safe degradation).

        After retrieval, emits rag_retrieval_items histogram metric per source type.
        """
        # PLAN-0067 W11-3: retrieval is optional on ChatPipeline (eval harness only).
        if self.retrieval is None:
            raise RuntimeError("retrieve() requires retrieval orchestrator (not set on this pipeline)")

        raw_items = await self.retrieval.retrieve(plan, resolved_query, request, embedding)

        # Record per-source-type item counts for the dashboard retrieval breakdown.
        _type_counts = _Counter(item.item_type.value for item in raw_items)
        for _source_type, _count in _type_counts.items():
            rag_retrieval_items.labels(source_type=_source_type).observe(_count)

        return raw_items

    # ── Step 8: Reranking ────────────────────────────────────────────────────

    async def rerank_items(self, query: str, items: list) -> list:
        """Step 8: Cross-encoder reranking over the top-30 fused candidates.

        Slices to items[:30] before passing to the reranker (the reranker
        is only expected to receive at most 30 candidates — fusion already
        caps at 30, but we guard here for safety).
        """
        return await self.reranker.rerank(query, items[:30])  # type: ignore[no-any-return]

    # ── Steps 9-10: Contradiction assembly + context assembly + prompt build ──

    def build_prompt(
        self,
        reranked: list,
        history: list,
        query: str,
        sub_questions: tuple,
        intent: Any,
        type_counts: Any,  # Counter[str]
    ) -> tuple:  # (prompt: str, contradiction_refs: list, context_block: str)
        """Steps 9-10: Assemble contradiction block, context block, and full LLM prompt.

        Step 9 — Contradiction detection:
          The contradiction_refs list starts empty (filled from retrieved
          contradiction items). ContradictionAssembler formats them for the prompt.
          Emits rag_contradiction_surfaced metric per contradiction ref.

        Step 10 — Prompt construction:
          Assembles numbered context block from reranked items, then builds the
          full prompt using PromptBuilder (intent-specific system instruction +
          context + contradictions + history + query).

        Returns (prompt_str, contradiction_refs, context_block_str).
        """
        # Step 9: Build contradiction evidence block.
        # contradiction_refs is always an empty list here because the pipeline
        # currently does not extract contradiction items separately from retrieval.
        # The hook is preserved so PLAN-0067 can wire it later.
        contradiction_refs: list = []
        contradiction_block = self.contradiction_assembler.build(contradiction_refs)
        for _ref in contradiction_refs:
            _claim_type = getattr(_ref, "claim_type", "unknown")
            rag_contradiction_surfaced.labels(claim_type=str(_claim_type)).inc()

        # Step 10: Assemble numbered context block from reranked evidence.
        context_block = self.context_assembler.assemble(reranked)

        _counts = RetrievalCounts(
            n_context_items=len(reranked),
            n_chunks=type_counts.get("chunk", 0),
            n_rel=type_counts.get("relation", 0),
            n_events=type_counts.get("event", 0),
            n_fin=type_counts.get("financial", 0),
        )

        prompt = self.prompt_builder.build(
            context_block=context_block,
            conversation_history=history,
            rephrased_query=query,
            sub_questions=sub_questions,
            contradiction_block=contradiction_block,
            intent=intent,
            retrieval_counts=_counts,
        )

        return prompt, contradiction_refs, context_block

    # ── Step 11: LLM streaming ───────────────────────────────────────────────

    async def stream_llm(self, prompt: str) -> AsyncGenerator[tuple[str, str], None]:
        """Step 11: Stream LLM response with real-time <think> block filtering.

        Creates a new _ThinkBlockFilter per call (stateful — one instance per request).
        Iterates self.llm_chain.stream(prompt, max_tokens=4000, temperature=0.1).

        Yields (filtered_chunk, raw_chunk) tuples where:
        - filtered_chunk: the portion of raw_chunk that should be shown to users
                          (may be empty string if the chunk was suppressed)
        - raw_chunk: the original unfiltered chunk from the LLM

        After iteration, flushes any buffered content from the filter.
        """
        think_filter = _ThinkBlockFilter()

        async for chunk in self.llm_chain.stream(prompt, max_tokens=4000, temperature=0.1):
            filtered = think_filter.feed(chunk)
            yield filtered, chunk

        # Flush any content that was held in the buffer awaiting tag boundary resolution.
        remaining = think_filter.flush()
        if remaining:
            yield remaining, ""

    # ── Step 12: Output processing ───────────────────────────────────────────

    def process_output(self, full_text: str, reranked: list) -> tuple:  # (str, list)
        """Step 12: Process raw LLM output into a clean answer with citations.

        Delegates to OutputProcessor which:
        1. Strips <think>/<reasoning>/<scratchpad> blocks (safety net in addition
           to the streaming filter — catches blocks that span chunk boundaries).
        2. Redacts PII detected in the output.
        3. Parses [N] citation markers.
        4. Builds the Citation[] list from reranked items.

        Returns (answer: str, citations: list[Citation]).
        """
        return self.output_processor.process(full_text, reranked)

    # ── Step 13: Chat persistence ────────────────────────────────────────────

    async def persist_chat(
        self,
        thread_id: Any,
        user_message: str,
        assistant_response: AssistantResponse,
        uow: Any,
        tenant_id: Any,
        user_id: Any,
    ) -> tuple:  # (user_msg_id: UUID, asst_msg_id: UUID)
        """Step 13: Persist user + assistant messages to the database.

        On success: returns (user_msg_id, asst_msg_id) from ChatPersistenceUseCase.
        On exception: logs the error and returns two new fallback UUIDs so the
        caller can still emit a complete SSE metadata event.
        """
        try:
            return await self.persistence.execute(
                thread_id=thread_id,
                user_message=user_message,
                assistant_response=assistant_response,
                uow=uow,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        except Exception as exc:
            log.error("chat_persistence_failed", error=str(exc))  # type: ignore[no-any-return]
            # Return fallback UUIDs so the caller can emit a valid metadata event
            # even when persistence fails (best-effort — the answer was already sent).
            _fallback = _new_uuid()
            return _fallback, _new_uuid()

    # ── Post-Step 13: Best-effort cache write ────────────────────────────────

    async def write_completion_cache(
        self,
        message: str,
        thread_id: Any,
        answer: str,
        citations: list,
    ) -> None:
        """Best-effort completion cache write. Swallows all exceptions silently.

        Stores the completed answer + citation list so identical future requests
        can be served from cache (24-hour TTL, keyed by message + thread_id hash).
        """
        try:
            await self.cache.set(
                message,
                thread_id,
                {"answer": answer, "citations": [c.__dict__ if hasattr(c, "__dict__") else c for c in citations]},
            )
        except Exception:
            log.debug("completion_cache_write_failed")  # type: ignore[no-any-return]


# ── Module-level helpers ──────────────────────────────────────────────────────


def _new_uuid() -> Any:
    """Generate a new UUIDv7 (used for fallback message IDs in persist_chat)."""
    from common.ids import new_uuid7  # type: ignore[import-untyped]

    return new_uuid7()
