"""Chat orchestrator use case - top-level pipeline coordinator (T-F-4-02).

Delegates all 13 pipeline steps to ChatPipeline (PLAN-0077 Wave C).
The class is named ChatOrchestratorUseCase for consistency with other use cases in this layer.

PLAN-0066 Wave H: optional tool-use loop inserted after initial retrieval (steps 11+).
When _tool_executor is set, the system prompt includes the capability manifest and the
LLM may emit tool_use JSON blocks. Those blocks trigger ToolExecutor.execute_all() to
fetch temporal data (OHLCV history, quarterly fundamentals) from S3Port and inject the
results into the retrieved items before the final LLM turn.

The loop is capped at 2 LLM turns (1 tool round + 1 final answer).
When _tool_executor is None (default), the classical pipeline is unchanged.
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
    from rag_chat.application.pipeline.tool_executor import ToolExecutor, ToolUseBlock
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.chat import ChatRequest, RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum LLM turns in the tool-use loop (1 tool call round + 1 final answer)
_MAX_TOOL_TURNS = 2


def _parse_tool_use_blocks(response_text: str) -> list[ToolUseBlock]:
    """Parse tool_use JSON blocks from LLM response text.

    The LLM is instructed to emit JSON blocks shaped like:
        {"type": "tool_use", "name": "get_price_history",
         "input": {"ticker": "AAPL", "from_date": "2026-02-03", ...}}

    WHY balanced-brace scan: the input field may contain a nested JSON object,
    so a simple [^{}]* regex fails. We scan for every `{` in the text, extract
    the balanced brace span, and try json.loads on each candidate object.
    """
    # Import here to avoid circular imports at module level
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    blocks: list[ToolUseBlock] = []

    # Walk through the text finding balanced {…} spans
    i = 0
    while i < len(response_text):
        if response_text[i] != "{":
            i += 1
            continue
        # Try to find the matching closing brace
        depth = 0
        j = i
        in_string = False
        escape_next = False
        while j < len(response_text):
            ch = response_text[j]
            if escape_next:
                escape_next = False
                j += 1
                continue
            if ch == "\\" and in_string:
                escape_next = True
                j += 1
                continue
            if ch == '"':
                in_string = not in_string
                j += 1
                continue
            if not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = response_text[i : j + 1]
                        try:
                            raw = json.loads(candidate)
                            if (
                                isinstance(raw, dict)
                                and raw.get("type") == "tool_use"
                                and "name" in raw
                                and "input" in raw
                            ):
                                blocks.append(
                                    ToolUseBlock(
                                        name=raw["name"],
                                        input=raw.get("input", {}),
                                        tool_use_id=raw.get("id", ""),
                                    )
                                )
                        except (json.JSONDecodeError, KeyError, ValueError):
                            pass
                        break
            j += 1
        i += 1
    return blocks


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

    def __init__(
        self,
        pipeline: ChatPipeline,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self._pipeline = pipeline
        # PLAN-0066 Wave H: optional tool-use executor.
        # When None, the classical retrieval pipeline is unchanged (default path).
        # When set, the system prompt includes the capability manifest and the loop
        # activates on tool_use blocks in the LLM response.
        self._tool_executor = tool_executor

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

        # PLAN-0066 Wave H: when tool_executor is active, append the capability manifest
        # to the prompt so the LLM can emit tool_use JSON blocks at generation time.
        # WHY append (not prepend): the context block is the most important content;
        # the manifest is a capability declaration appended as a postscript.
        if self._tool_executor is not None:
            prompt = (
                prompt
                + "\n\n"
                + self._tool_executor._registry.to_system_prompt_section()
                + "\n\nIf you need temporal data (price history or fundamentals), emit a tool_use JSON block. "
                "Otherwise answer directly using the context above."
            )

        # Step 11: LLM first turn (with optional tool-use loop)
        full_text = ""
        provider_name = "unknown"
        _tool_loop_active = self._tool_executor is not None
        _tool_turn_count = 0

        # Collect first LLM response (non-streaming for tool detection; stream if no tools)
        # WHY: we need the full first response to detect tool_use blocks before streaming
        # tokens to the client. If no tool blocks are found, we stream from the collected
        # response. The 2-turn cap (_MAX_TOOL_TURNS) prevents infinite loops.
        if _tool_loop_active:
            # First turn: collect full text to detect tool_use blocks
            first_full_text = ""
            async for _filtered, raw in p.stream_llm(prompt):
                first_full_text += raw
            provider_name = p.llm_chain.last_provider_name
            _tool_turn_count += 1

            # Detect tool_use blocks in first response
            tool_calls = _parse_tool_use_blocks(first_full_text)

            if tool_calls:
                # Emit tool_call SSE events BEFORE executing (T-W10-H-04)
                for tc in tool_calls:
                    yield p.emitter.emit_tool_call(tc.name, tc.input)

                # Execute all tool calls concurrently (T-W10-H-02)
                tool_items = await self._tool_executor.execute_all(tool_calls)  # type: ignore[union-attr]

                # Emit tool_result SSE events AFTER execution (T-W10-H-04)
                for tc, item in zip(tool_calls, tool_items, strict=False):
                    yield p.emitter.emit_tool_result(tc.name, item is not None)

                # All-tools-failed guard (PLAN-0066 Wave H §T-W10-H-03):
                # If every tool call returned None, fall back to classical path.
                # Never produce a second LLM turn with zero tool context — the LLM
                # would hallucinate. Use the first_full_text as the final answer.
                non_none_items: list[RetrievedItem] = [i for i in tool_items if i is not None]
                if not non_none_items:
                    log.warning(
                        "all_tools_failed",
                        tool_count=len(tool_calls),
                        query=request.message[:100],
                    )
                    # Fall back: treat first_full_text as the final answer (classical context)
                    full_text = first_full_text
                elif _tool_turn_count < _MAX_TOOL_TURNS:
                    # Inject tool results and run second LLM turn
                    reranked = list(reranked) + non_none_items
                    _type_counts.update(item.item_type.value for item in non_none_items)
                    tool_prompt, _contradiction_refs2, _ctx2 = p.build_prompt(
                        reranked,
                        conversation_history,
                        effective_query,
                        tuple(sub_questions),
                        intent,
                        _type_counts,
                    )
                    # Append prior LLM exchange so the second turn has context
                    tool_prompt = tool_prompt + f"\n\nPrevious assistant response:\n{first_full_text}"
                    second_full_text = ""
                    async for filtered2, raw2 in p.stream_llm(tool_prompt):
                        second_full_text += raw2
                        if filtered2:
                            yield p.emitter.emit_token(filtered2)
                    provider_name = p.llm_chain.last_provider_name
                    _tool_turn_count += 1

                    # Second response: if it still contains tool_use blocks, treat as final
                    # (2-turn cap enforced — log warning so behavior is observable)
                    second_tool_calls = _parse_tool_use_blocks(second_full_text)
                    if second_tool_calls:
                        log.warning(
                            "tool_loop_cap_reached",
                            turn=_tool_turn_count,
                            blocks_found=len(second_tool_calls),
                        )
                    full_text = second_full_text
                else:
                    # Cap reached — treat first response as final
                    full_text = first_full_text
            else:
                # No tool_use blocks: stream the first response tokens to client
                # WHY RE-STREAM: the first turn was collected to check for tools.
                # Since no tools were called, emit all collected tokens now.
                if first_full_text:
                    yield p.emitter.emit_token(first_full_text)
                full_text = first_full_text
        else:
            # Classical path: streaming directly (tool_executor is None)
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
