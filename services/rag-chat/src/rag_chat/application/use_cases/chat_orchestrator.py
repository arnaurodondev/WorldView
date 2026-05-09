"""Chat orchestrator use case — tool-use only pipeline coordinator (PLAN-0067 W11-3).

PLAN-0067 W11-3: hard migration to tool-use as the ONLY path.
  - IntentClassifier, RetrievalPlanBuilder, ParallelRetrievalOrchestrator deleted.
  - No TOOL_USE_ENABLED flag — tool-use is unconditional (§0 A-1 binding).
  - ToolExecutorFactory injected at construction; ToolExecutor is per-request.
  - UoW used only at start (history load) and end (persistence) — not held
    across the tool loop to minimise connection pool pressure (§0 I-3).

Pipeline (tool-use only, 2-turn cap):
  0. Input validation
  1. Completion cache check
  2. Rate limit enforcement
  3. Load thread + history (UoW used only here and at persistence step)
  4. Entity resolution (S6)
  5. emit_thinking → first LLM turn non-streaming (chat_with_tools) → LLMToolResponse
  6. If tool_calls: emit_tool_call → execute_all → emit_tool_result (concurrent)
  7. All-tools-failed guard (prevents hallucination)
  8. Second LLM turn streaming (stream_chat with tool results injected)
  9. Output processing + citations
 10. Persist + cache → emit metadata + done

The all-tools-failed guard (step 7) MUST be preserved — if all tools return
empty/None the orchestrator emits an error event and DOES NOT call the second
LLM turn. Without this guard the LLM would produce answers from empty context.

Tool loop cap: _MAX_TOOL_TURNS = 2 (1 tool round + 1 final answer).
"""

from __future__ import annotations

import json
import time
from collections import Counter as _Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_cache_hits,
    rag_latency,
    rag_queries_total,
    rag_tool_call_latency_seconds,
    rag_tool_call_total,
    rag_tool_use_first_turn_latency_seconds,
    record_reranker_position_change,
)
from rag_chat.application.use_cases.persist_chat import AssistantResponse
from rag_chat.domain.entities.chat import ResolvedQuery  # noqa: F401 (preserved for public surface)
from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from rag_chat.application.pipeline.chat_pipeline import ChatPipeline
    from rag_chat.application.pipeline.tool_executor import ToolExecutorFactory, ToolUseBlock
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.domain.entities.chat import ChatRequest, RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum LLM turns in the tool-use loop (1 tool call round + 1 final answer).
# WHY 2: allowing unlimited turns risks infinite loops where the LLM keeps requesting
# tools indefinitely. Two turns (tool + answer) is sufficient for all current tools.
_MAX_TOOL_TURNS = 2

# Maximum characters for tool result text injected into LLM messages.
# WHY 4000: OHLCV data for a year at ~50 chars/row ≈ 12,600 chars — well beyond
# most context windows. Cap prevents context overflow (BP-225 class).
_TOOL_RESULT_MAX_CHARS = 4000


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

    After PLAN-0067 W11-3 this class drives the tool-use path exclusively.
    IntentClassifier, RetrievalPlanBuilder, and ParallelRetrievalOrchestrator have
    been deleted — the LLM now decides what data to fetch via tool_use blocks,
    replacing static intent → retrieval plan dispatch.

    The class still delegates to ChatPipeline for the shared steps that remain
    unchanged: input validation, cache, rate limit, history load, entity resolution,
    HyDE expansion, graph enrichment, fusion, reranking, prompt building, output
    processing, and persistence.
    """

    def __init__(
        self,
        pipeline: ChatPipeline,
        tool_executor_factory: ToolExecutorFactory | None = None,
    ) -> None:
        self._pipeline = pipeline
        # ToolExecutorFactory is a singleton — ToolExecutor is per-request.
        # WHY factory pattern: shared collaborators (HTTP clients, registry) are expensive;
        # auth context (user_id, tenant_id, jwt) is per-request and must not bleed.
        # When None (legacy DI or tests), a default executor is built at request time.
        self._tool_factory = tool_executor_factory

    async def execute_streaming(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the full tool-use pipeline, yielding SSE events as they occur.

        UoW note (§0 I-3): the UoW is held by the route handler (via make_write_uow)
        for the duration of the SSE stream. History load happens at the start of the
        stream; persistence happens at the end. The tool loop (steps 5-8) does NOT
        perform any UoW operations — it only calls upstream HTTP services — so no
        DB connection is held while tool calls execute.
        """
        start = datetime.now(tz=UTC)
        p = self._pipeline  # shorthand

        # ── Step 0: Input validation ─────────────────────────────────────────────
        validated_message = await p.validate_input(request.message)

        # ── Step 1: Completion cache check ──────────────────────────────────────
        cached = await p.check_cache(request.message, request.thread_id)
        if cached:
            rag_cache_hits.labels(cache_type="completion").inc()
            yield p.emitter.emit_status("cache_hit")
            yield p.emitter.emit_token(cached.get("answer", ""))
            yield p.emitter.emit_citations([])
            yield p.emitter.emit_contradictions([])
            return

        # ── Step 2: Rate limit ───────────────────────────────────────────────────
        await p.check_rate_limit(request.tenant_id)

        yield p.emitter.emit_status("loading_context")

        # ── Step 3: Load conversation history (UoW — read only) ─────────────────
        # The UoW is not used again until persistence (step 10).
        # Tool loop calls (steps 5-8) are pure HTTP — no DB access.
        conversation_history = await p.load_history(request.thread_id, request.user_id, request.tenant_id, uow)

        yield p.emitter.emit_status("entity_resolution")

        # ── Step 4: Entity resolution ────────────────────────────────────────────
        entities = await p.resolve_entities(validated_message)

        # ── Step 5-8: Tool-use path ───────────────────────────────────────────────
        # Build per-request ToolExecutor from factory (or a minimal default).
        if self._tool_factory is not None:
            tool_executor = self._tool_factory.for_request(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                internal_jwt=None,  # JWT forwarding handled inside S1Port adapter
            )
        else:
            # Minimal default for tests/legacy DI that haven't been updated yet.
            from rag_chat.application.pipeline.tool_executor import ToolExecutor, build_default_registry

            tool_executor = ToolExecutor(
                registry=build_default_registry(),
                s3=None,  # type: ignore[arg-type]
            )

        # ── Step 5: emit_thinking + first LLM turn ────────────────────────────────
        yield p.emitter.emit_thinking(stage="tool_classification")

        # Build tool definitions from registry (if method available — optional API).
        # to_tool_definitions() returns OpenAI-format function schemas; if not available,
        # the LLM relies on the system prompt manifest section instead.
        tool_defs = None
        if hasattr(tool_executor._registry, "to_tool_definitions"):
            tool_defs = tool_executor._registry.to_tool_definitions()

        system_prompt = (
            tool_executor._registry.to_system_prompt_section()
            + "\n\nYou are a market intelligence assistant with access to the tools listed above. "
            "Use them to retrieve precise data before answering. "
            "If a tool returns no data, acknowledge that in your answer."
        )

        # Assemble OpenAI-format messages for the structured call.
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "")
            if role is not None:
                messages.append({"role": getattr(role, "value", str(role)), "content": content})
        messages.append({"role": "user", "content": request.message})

        first_turn_start = time.monotonic()
        try:
            llm_response = await p.llm_chain.chat_with_tools(
                messages,
                tools=tool_defs if tool_defs else None,
                max_tokens=1024,
                temperature=0.1,
            )
        except Exception as exc:
            log.error("tool_use_first_turn_failed", error=str(exc))  # type: ignore[no-any-return]
            yield p.emitter.emit_error("llm_first_turn_failed", "Unable to process request")
            return
        finally:
            first_turn_latency = time.monotonic() - first_turn_start
            rag_tool_use_first_turn_latency_seconds.observe(first_turn_latency)

        provider_name = p.llm_chain.last_provider_name

        # ── Step 6: Tool calls → execute → emit results ──────────────────────────
        tool_calls: list[ToolUseBlock] = getattr(llm_response, "tool_calls", None) or []
        non_none_items: list[RetrievedItem] = []
        reranked: list[RetrievedItem] = []
        contradiction_refs: list = []
        intent = QueryIntent.GENERAL
        _type_counts: _Counter = _Counter()

        if tool_calls:
            # Emit tool_call SSE events BEFORE executing so the frontend spinner appears immediately.
            for tc in tool_calls:
                # Build safe input_summary (strip keys that might contain PII).
                _safe_input = {k: v for k, v in tc.input.items() if k not in {"query", "text"}}
                yield p.emitter.emit_tool_call(tc.name, _safe_input)

            # Execute all tool calls concurrently (asyncio.gather inside execute_all).
            _tool_t0 = time.monotonic()
            tool_items = await tool_executor.execute_all(tool_calls)
            _tool_latency = time.monotonic() - _tool_t0

            # Flatten results (PLAN-0067 W11-2: multi-result tools return list[RetrievedItem]).
            _flat_items: list[RetrievedItem] = []
            for _item in tool_items:
                if isinstance(_item, list):
                    _flat_items.extend(_item)
                elif _item is not None:
                    _flat_items.append(_item)
            non_none_items = _flat_items

            # PLAN-0082 Wave B: detect action_pending items from write-action tools.
            # These items require user confirmation before execution.  We emit a
            # pending_action SSE event for each one and remove them from the normal
            # retrieval context (they must not go to the LLM for a second-turn answer).
            from rag_chat.domain.enums import ItemType as _ItemType

            _action_pending_items = [i for i in non_none_items if i.item_type == _ItemType.action_pending]
            _retrieval_items = [i for i in non_none_items if i.item_type != _ItemType.action_pending]
            non_none_items = _retrieval_items

            for _pending in _action_pending_items:
                # Extract proposal_id from the item text (JSON-encoded params).
                try:
                    _params = json.loads(_pending.text)
                except Exception:
                    _params = {}
                _proposal_id = _params.get("proposal_id", str(_pending.item_id))
                _tool_name = _pending.item_id.split(":")[1] if ":" in _pending.item_id else "create_alert"
                _description = _params.get("description") or f"Create alert: {_params.get('condition', '?')}"
                # Extract safe display params (never include user_id or tenant_id).
                _display_params = {
                    k: v for k, v in _params.items() if k in {"entity_id", "condition", "threshold", "severity"}
                }
                yield p.emitter.emit_pending_action(
                    proposal_id=_proposal_id,
                    tool_name=_tool_name,
                    description=_description,
                    params=_display_params,
                )

            # Emit tool_result events and record per-tool metrics.
            for tc, _item in zip(tool_calls, tool_items, strict=False):
                _item_list = _item if isinstance(_item, list) else ([_item] if _item is not None else [])
                _count = len(_item_list)
                _status = "ok" if _count > 0 else ("empty" if _item is not None else "error")
                rag_tool_call_total.labels(tool_name=tc.name, status=_status).inc()
                # Distribute shared latency evenly across parallel calls.
                rag_tool_call_latency_seconds.labels(tool_name=tc.name).observe(_tool_latency / max(len(tool_calls), 1))
                yield p.emitter.emit_tool_result(tc.name, status=_status, item_count=_count)

        # ── Step 7: All-tools-failed guard ───────────────────────────────────────
        # If the LLM requested tools but ALL returned empty/None AND there are no
        # pending action proposals, do NOT call the second LLM turn — the model
        # would hallucinate from empty context.
        # PLAN-0082 QA fix C-1: exempt action_pending items from the "all failed"
        # check.  When the only tool call is create_alert, non_none_items is empty
        # (action_pending items were moved to _action_pending_items above), but the
        # request was NOT a failure — the user has been presented a confirmation
        # modal.  We must NOT emit all_tools_failed in that case.
        if tool_calls and not non_none_items and not _action_pending_items:
            log.warning(  # type: ignore[no-any-return]
                "all_tools_failed",
                tool_count=len(tool_calls),
                tools=[tc.name for tc in tool_calls],
                query=request.message[:100],
            )
            yield p.emitter.emit_error("all_tools_failed", "Unable to retrieve relevant data")
            return

        # ── Step 8: Second LLM turn (streaming) ──────────────────────────────────
        full_text = ""
        if tool_calls and non_none_items:
            # Rerank + build context block from tool results.
            _type_counts = _Counter(item.item_type.value for item in non_none_items)
            reranked = await p.rerank_items(request.message, non_none_items)
            if non_none_items and reranked:
                record_reranker_position_change(non_none_items[0].item_id != reranked[0].item_id)

            _prompt, contradiction_refs, _context_block = p.build_prompt(
                reranked,
                [],  # history already in messages; not repeated here
                request.message,
                (),  # sub_questions not available in tool-use path
                intent,
                _type_counts,
            )

            # Inject assistant turn (tool_calls intent) + tool results as user follow-up.
            messages.append(
                {
                    "role": "assistant",
                    "content": (getattr(llm_response, "text", "") or ""),
                    "tool_calls": [
                        {
                            "id": getattr(tc, "tool_use_id", tc.name),
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            # WHY user role for context: tool_result role is provider-specific;
            # a user message with the assembled context block works uniformly.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Here is the data retrieved by the tools:\n\n"
                        + _context_block[:_TOOL_RESULT_MAX_CHARS]
                        + "\n\nPlease answer the original question using this data."
                    ),
                }
            )

            try:
                async for chunk in p.llm_chain.stream_chat(
                    messages,
                    max_tokens=4000,
                    temperature=0.1,
                ):
                    full_text += chunk
                    if chunk:
                        yield p.emitter.emit_token(chunk)
            except Exception as exc:
                log.error("tool_use_second_turn_failed", error=str(exc))  # type: ignore[no-any-return]
                yield p.emitter.emit_error("llm_second_turn_failed", "Unable to generate answer")
                return
            provider_name = p.llm_chain.last_provider_name

        else:
            # No tool calls — LLM answered directly from its training data.
            # Stream the text field immediately.
            full_text = getattr(llm_response, "text", "") or ""
            if full_text:
                yield p.emitter.emit_token(full_text)

        # ── Step 9: Output processing + citations ────────────────────────────────
        answer, citations = p.process_output(full_text, reranked)

        yield p.emitter.emit_citations(citations)
        yield p.emitter.emit_contradictions(contradiction_refs)

        # ── Step 10: Persist + cache + metrics ───────────────────────────────────
        thread_id: UUID = request.thread_id or _new_thread_id()
        latency_ms = int((datetime.now(tz=UTC) - start).total_seconds() * 1000)
        _model_id = _resolve_model_id(p.llm_chain, provider_name)
        token_count_in_est = len(request.message) // 4

        _user_msg_id, asst_msg_id = await p.persist_chat(
            thread_id=thread_id,
            user_message=request.message,
            assistant_response=AssistantResponse(
                content=answer,
                intent=intent,
                resolved_entities=tuple(entities),
                retrieval_plan=None,
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

        await p.write_completion_cache(request.message, request.thread_id, answer, citations)

        _total_latency_s = (datetime.now(tz=UTC) - start).total_seconds()
        rag_queries_total.labels(
            intent=intent.value,
            provider=provider_name,
            tenant_id=str(request.tenant_id),
        ).inc()
        rag_latency.labels(intent=intent.value, step="total").observe(_total_latency_s)

        yield p.emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)
        yield p.emitter.emit_done()

    async def execute_sync(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> dict:  # type: ignore[type-arg]
        """Run the full pipeline synchronously — collects all SSE events and returns final answer."""
        answer = ""
        citations: list = []
        contradictions: list = []
        metadata: dict = {}  # type: ignore[type-arg]

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

        # Safety net: strip any residual <think> blocks from accumulated token stream.
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
