"""Chat orchestrator use case — multi-turn agent loop pipeline coordinator.

E-6: AgentBudget replaces _MAX_TOOL_TURNS=2. The orchestrator now runs up to
  budget.max_iterations tool rounds, with soft-budget surrender for latency,
  consecutive errors, and a hard cap on iterations.

E-7: Citation egress allowlist. After the final answer is generated, any
  entity/article references that were NOT grounded in tool results are
  scrubbed from the answer before reaching the user.

E-12: ChatAuditLogger records per-turn structured audit data (tool outcomes,
  iteration count, answer hash, total latency) to chat_audit_log.

Pipeline (multi-turn agent loop):
  0. Input validation (Layer 1 regex + PII; Layer 2 LLM semantic if wired)
  1. Completion cache check
  2. Rate limit enforcement
  3. Load thread + history (UoW used only here and at persistence step)
  4. Entity resolution (S6)
  5. emit_thinking → loop:
       a. LLM turn non-streaming (chat_with_tools) → LLMToolResponse
       b. If no tool_calls: stream text directly → break
       c. emit_tool_call → execute_all → emit_tool_result (concurrent)
       d. All-tools-failed guard on iteration 0
       e. Soft budget checks (consecutive errors, cumulative latency)
       f. Inject tool results into messages for next iteration
     After loop: inject surrender message if budget exceeded
  6. Final streaming answer (if there were tool calls)
  7. E-7 citation scrubbing (unseen entity/article refs → [ref:redacted])
  8. Output processing + citations
  9. E-12 audit log finalization (try/finally — never propagates)
 10. Persist + cache → emit metadata + done

The all-tools-failed guard (on iteration 0 only) MUST be preserved — if all
tools return empty/None on the first iteration and there are no pending actions,
emit an error and stop. Without this guard the LLM hallucinates from empty context.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter as _Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_agent_iterations,
    rag_budget_exceeded_total,
    rag_cache_hits,
    rag_citations_scrubbed_total,
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

# Maximum characters for tool result text injected into LLM messages.
# WHY 4000: OHLCV data for a year at ~50 chars/row ≈ 12,600 chars — well beyond
# most context windows. Cap prevents context overflow (BP-225 class).
_TOOL_RESULT_MAX_CHARS = 4000

# ── E-6: Agent budget governance ─────────────────────────────────────────────


@dataclass
class AgentBudget:
    """Governance parameters for the multi-turn agent tool loop.

    E-6: replaces the old _MAX_TOOL_TURNS = 2 constant. Each field is a budget
    knob that controls when the loop surrenders and forces a final answer.

    Soft budgets trigger a surrender message (the LLM answers with what it has).
    Hard budgets (max_iterations) just stop the loop and force the final turn.

    Field defaults are tuned for the production workload:
      - max_tokens_per_iter=2048: enough for a tool-call decision + reasoning
      - max_tokens_final=8000: generous budget for a well-cited final answer
      - max_tool_latency_s=30.0: cumulative wall-clock across all tool rounds
      - max_per_tool_s=30.0: per-tool asyncio.wait_for (handled in executor)
      - max_iterations=8: allows up to 8 tool rounds before forcing an answer
      - max_consecutive_errors=2: 2 rounds of all-fail → surrender (avoids
        the model retrying a broken tool indefinitely)
    """

    max_tokens_per_iter: int = 2048
    max_tokens_final: int = 8000
    max_tool_latency_s: float = 30.0
    max_per_tool_s: float = 30.0
    max_iterations: int = 8
    max_consecutive_errors: int = 2


# ── E-7: Citation egress helpers ─────────────────────────────────────────────

# Match entity:UUID and article:UUID citation markers that the LLM may embed.
# WHY lowercase the match group: IDs in tool results may be stored in any case;
# we normalise to lowercase for comparison with the seen_ids set.
_ENTITY_REF_RE = re.compile(r"entity:[0-9a-f-]{36}", re.IGNORECASE)
_ARTICLE_REF_RE = re.compile(r"article:[0-9a-f-]{36}", re.IGNORECASE)


def _scrub_unseen_refs(text: str, seen_ids: set[str]) -> tuple[str, int]:
    """Replace entity/article refs not in seen_ids with [ref:redacted].

    Args:
        text: The raw LLM answer text.
        seen_ids: Lowercase IDs harvested from tool results.

    Returns:
        (scrubbed_text, count) where count is the number of refs scrubbed.
    """
    count = 0

    def _replace_if_unseen(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal count
        ref: str = m.group(0)
        if ref.lower() in seen_ids:
            return ref
        count += 1
        return "[ref:redacted]"

    text = _ENTITY_REF_RE.sub(_replace_if_unseen, text)
    text = _ARTICLE_REF_RE.sub(_replace_if_unseen, text)
    return text, count


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

    E-6: multi-turn agent loop with AgentBudget governance.
    E-7: citation egress allowlist scrubbing.
    E-12: per-turn structured audit log.
    """

    def __init__(
        self,
        pipeline: ChatPipeline,
        tool_executor_factory: ToolExecutorFactory | None = None,
        budget: AgentBudget | None = None,
        write_factory: Any = None,
    ) -> None:
        self._pipeline = pipeline
        # ToolExecutorFactory is a singleton — ToolExecutor is per-request.
        # WHY factory pattern: shared collaborators (HTTP clients, registry) are expensive;
        # auth context (user_id, tenant_id, jwt) is per-request and must not bleed.
        # When None (legacy DI or tests), a default executor is built at request time.
        self._tool_factory = tool_executor_factory
        # E-6: budget governs the multi-turn loop. None → use defaults.
        self._budget = budget or AgentBudget()
        # E-12: write_factory for ChatAuditLogger.finalize(). None → audit skipped.
        self._write_factory = write_factory

    async def execute_streaming(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run the full multi-turn agent loop, yielding SSE events as they occur.

        E-6: The tool loop runs up to budget.max_iterations rounds. Each round:
          1. LLM non-streaming turn (chat_with_tools)
          2. If no tool calls → stream text and break
          3. Execute tools concurrently, emit events
          4. Check soft budgets (consecutive errors, cumulative latency)
          5. Inject results into messages for next iteration

        E-7: After full_text is assembled, scrub unseen entity/article refs.

        E-12: ChatAuditLogger buffers tool events and flushes in finally block.

        UoW note: held only for history load (step 3) and persistence (step 9).
        Tool loop HTTP calls do NOT use UoW — no DB connection held while tools run.
        """
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        start = datetime.now(tz=UTC)
        p = self._pipeline  # shorthand
        budget = self._budget

        # E-12: initialise audit logger for this turn.
        _turn_id = _new_thread_id()  # UUIDv7
        audit = ChatAuditLogger(
            turn_id=_turn_id,
            thread_id=request.thread_id or _turn_id,
            user_id=request.user_id,
        )

        try:
            async for event in self._execute_streaming_inner(request, uow, p, budget, audit, start):
                yield event
        finally:
            # E-12: finalize audit log — never propagates to user.
            if self._write_factory is not None:
                await audit.finalize(
                    answer=getattr(audit, "_last_answer", ""),
                    session_factory=self._write_factory,
                )

    async def _execute_streaming_inner(
        self,
        request: ChatRequest,
        uow: RagUnitOfWorkPort,
        p: ChatPipeline,
        budget: AgentBudget,
        audit: Any,
        start: datetime,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Inner generator — contains the full pipeline logic.

        Split from execute_streaming so the try/finally in execute_streaming
        correctly wraps all yields without Python generator/finally interaction issues.
        """
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
        conversation_history = await p.load_history(request.thread_id, request.user_id, request.tenant_id, uow)

        yield p.emitter.emit_status("entity_resolution")

        # ── Step 4: Entity resolution ────────────────────────────────────────────
        entities = await p.resolve_entities(validated_message)

        # ── Step 5-8: Multi-turn agent loop ───────────────────────────────────────
        from rag_chat.application.pipeline.tool_executor import EntityContext

        _primary = entities[0] if entities else None
        entity_context = (
            EntityContext(
                entity_id=_primary.entity_id,
                ticker=_primary.ticker or "",
                name=_primary.canonical_name,
            )
            if _primary is not None
            else None
        )

        if self._tool_factory is not None:
            tool_executor = self._tool_factory.for_request(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                internal_jwt=None,
                entity_context=entity_context,
            )
        else:
            from rag_chat.application.pipeline.tool_executor import ToolExecutor, build_default_registry

            tool_executor = ToolExecutor(
                registry=build_default_registry(),
                s3=None,  # type: ignore[arg-type]
            )

        # Build tool definitions + system prompt (same as before).
        yield p.emitter.emit_thinking(stage="tool_classification")

        tool_defs = None
        if hasattr(tool_executor._registry, "to_tool_definitions"):
            tool_defs = tool_executor._registry.to_tool_definitions()

        from common.time import utc_now  # type: ignore[import-untyped]

        _today = utc_now().date().isoformat()

        _entity_map_section = ""
        if entities:
            _emap_lines = []
            for _ent in entities:
                _ticker_str = f", ticker: {_ent.ticker}" if _ent.ticker else ""
                _emap_lines.append(
                    f'- "{_ent.canonical_name}": entity_id={_ent.entity_id}' f" (type: {_ent.entity_type}{_ticker_str})"
                )
            _entity_map_section = "\n\nEntities resolved from this query:\n" + "\n".join(_emap_lines)

        # ── E-1: Strict tool-use prompt from libs/prompts ─────────────────
        # The old inline prompt explicitly invited training-knowledge
        # supplement for relationship facts, which the LLM happily extended
        # to invent revenue, EPS, P/E, and quarter labels. The new prompt
        # (libs/prompts/chat/tool_use.py) is structurally identical in its
        # CITATIONS section but adds a hard FORBIDDEN block + structural-
        # only public-knowledge carve-out. See PLAN-0093 T-E-1-01.
        from prompts.chat.tool_use import get_tool_use_system_prompt  # type: ignore[import-untyped]

        # Initial intent is GENERAL — we re-infer after the first tool batch
        # so the per-intent style addendum reflects what the LLM actually
        # asked the tools to fetch (E-1 T-E-1-02).
        intent = QueryIntent.GENERAL
        _tool_use_prompt = get_tool_use_system_prompt(
            intent=intent.value,
            today_iso=_today,
            entity_map_section=_entity_map_section,
        )
        system_prompt = tool_executor._registry.to_system_prompt_section() + "\n\n" + _tool_use_prompt

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "")
            if role is not None:
                messages.append({"role": getattr(role, "value", str(role)), "content": content})
        messages.append({"role": "user", "content": request.message})

        # ── E-6: Multi-turn agent loop state ──────────────────────────────────
        # intent is initialised above (defaults to GENERAL); we re-infer it
        # after the first tool-call batch (E-1 T-E-1-02) so the per-intent
        # rerank weights + prompt addendum + metrics labels reflect what the
        # LLM actually requested via tool calls.
        non_none_items: list[RetrievedItem] = []
        reranked: list[RetrievedItem] = []
        contradiction_refs: list = []
        _type_counts: _Counter = _Counter()
        full_text = ""
        provider_name = p.llm_chain.last_provider_name

        # E-7: accumulate IDs from tool results across all iterations.
        seen_item_ids: set[str] = set()

        # Budget tracking
        consecutive_errors = 0
        cumulative_tool_latency = 0.0
        had_tool_calls = False
        iteration_count = 0

        # ── E-6: Agent loop ───────────────────────────────────────────────────
        for iteration in range(budget.max_iterations):
            # LLM non-streaming turn to decide next tool calls
            iter_turn_start = time.monotonic()
            try:
                llm_response = await p.llm_chain.chat_with_tools(
                    messages,
                    tools=tool_defs if tool_defs else None,
                    max_tokens=budget.max_tokens_per_iter,
                    temperature=0.1,
                )
            except Exception as exc:
                log.error("tool_use_first_turn_failed", error=str(exc), iteration=iteration)  # type: ignore[no-any-return]
                yield p.emitter.emit_error("llm_first_turn_failed", "Unable to process request")
                return
            finally:
                # Record first-turn latency only on iteration 0 (original metric semantics).
                if iteration == 0:
                    rag_tool_use_first_turn_latency_seconds.observe(time.monotonic() - iter_turn_start)

            provider_name = p.llm_chain.last_provider_name
            tool_calls: list[ToolUseBlock] = getattr(llm_response, "tool_calls", None) or []

            # ── LLM chose to answer directly (no tool calls) ─────────────────
            if not tool_calls:
                # Stream the direct text answer immediately.
                direct_text = getattr(llm_response, "text", "") or ""
                if direct_text:
                    yield p.emitter.emit_token(direct_text)
                full_text = direct_text
                # No tool calls on this iteration — nothing to add to messages.
                # Break out of the loop; we'll skip the streaming final turn below.
                break

            # ── Tool execution ────────────────────────────────────────────────
            had_tool_calls = True

            # ── E-1 T-E-1-02: infer intent from the first tool-call batch ─
            # We only re-infer on iteration 0 — subsequent rounds are LLM
            # refinements over data already retrieved, so the intent doesn't
            # change. The inferred intent is used for (a) the next prompt's
            # per-intent addendum, (b) the rerank pass, and (c) metrics +
            # audit log labels emitted later.
            if iteration == 0:
                from rag_chat.application.services.intent_inference import infer_intent

                intent = infer_intent(tool_calls)
                # Refresh the system message in-place so iteration 1 onward
                # uses the per-intent style addendum. messages[0] is always
                # the system prompt slot (set above before the loop began).
                messages[0] = {
                    "role": "system",
                    "content": (
                        tool_executor._registry.to_system_prompt_section()
                        + "\n\n"
                        + get_tool_use_system_prompt(
                            intent=intent.value,
                            today_iso=_today,
                            entity_map_section=_entity_map_section,
                        )
                    ),
                }

            # Emit tool_call SSE events before executing so the frontend spinner appears.
            for tc in tool_calls:
                _safe_input = {k: v for k, v in tc.input.items() if k not in {"query", "text"}}
                yield p.emitter.emit_tool_call(tc.name, _safe_input)

            # Execute all tool calls concurrently.
            _tool_t0 = time.monotonic()
            tool_items = await tool_executor.execute_all(tool_calls)
            _tool_latency = time.monotonic() - _tool_t0
            cumulative_tool_latency += _tool_latency

            # Flatten results.
            _flat_items: list[RetrievedItem] = []
            for _item in tool_items:
                if isinstance(_item, list):
                    _flat_items.extend(_item)
                elif _item is not None:
                    _flat_items.append(_item)
            _iter_items = _flat_items

            # ── E-7: harvest item IDs for the egress allowlist ────────────────
            # Collect entity_id / item_id / source_id from each tool result so
            # the citation scrubber knows which IDs were actually grounded.
            for _item_list in tool_items:
                _items = (
                    _item_list if isinstance(_item_list, list) else ([_item_list] if _item_list is not None else [])
                )
                for _it in _items:
                    # item_id may be "tool:price_history:AAPL" — also try splitting by ":"
                    _raw_id = getattr(_it, "item_id", None)
                    if _raw_id:
                        seen_item_ids.add(str(_raw_id).lower())
                    _src_id = getattr(_it, "source_id", None)
                    if _src_id:
                        seen_item_ids.add(str(_src_id).lower())

            # Separate action_pending items from retrieval items.
            from rag_chat.domain.enums import ItemType as _ItemType

            _action_pending_items = [i for i in _iter_items if i.item_type == _ItemType.action_pending]
            _retrieval_items = [i for i in _iter_items if i.item_type != _ItemType.action_pending]

            for _pending in _action_pending_items:
                try:
                    _params = json.loads(_pending.text)
                except Exception:
                    _params = {}
                _proposal_id = _params.get("proposal_id", str(_pending.item_id))
                _tool_name = _pending.item_id.split(":")[1] if ":" in _pending.item_id else "create_alert"
                _description = _params.get("description") or f"Create alert: {_params.get('condition', '?')}"
                _display_params = {
                    k: v for k, v in _params.items() if k in {"entity_id", "condition", "threshold", "severity"}
                }
                yield p.emitter.emit_pending_action(
                    proposal_id=_proposal_id,
                    tool_name=_tool_name,
                    description=_description,
                    params=_display_params,
                )

            # Emit tool_result events + record per-tool metrics + E-12 audit.
            _all_failed = True
            for tc, _item in zip(tool_calls, tool_items, strict=False):
                _item_list2 = _item if isinstance(_item, list) else ([_item] if _item is not None else [])
                _count = len(_item_list2)
                _status = "ok" if _count > 0 else ("empty" if _item is not None else "error")
                if _count > 0:
                    _all_failed = False
                rag_tool_call_total.labels(tool_name=tc.name, status=_status).inc()
                rag_tool_call_latency_seconds.labels(tool_name=tc.name).observe(_tool_latency / max(len(tool_calls), 1))
                yield p.emitter.emit_tool_result(tc.name, status=_status, item_count=_count)

                # E-12: record each tool call outcome.
                _success = _count > 0
                _latency_ms = int(_tool_latency / max(len(tool_calls), 1) * 1000)
                audit.record_tool_call(tc.name, success=_success, latency_ms=_latency_ms)

            # Add retrieval items to the accumulated non_none_items pool.
            non_none_items.extend(_retrieval_items)

            # ── All-tools-failed guard (iteration 0 only) ────────────────────
            # On the first iteration, if all tools fail and there are no pending
            # actions, emit error and stop. This prevents hallucination on empty context.
            # On subsequent iterations we use the consecutive_errors soft budget instead.
            if iteration == 0 and _all_failed and not _action_pending_items:
                log.warning(  # type: ignore[no-any-return]
                    "all_tools_failed",
                    tool_count=len(tool_calls),
                    tools=[tc.name for tc in tool_calls],
                    query=request.message[:100],
                )
                yield p.emitter.emit_error("all_tools_failed", "Unable to retrieve relevant data")
                return

            # ── E-6: Soft budget checks ───────────────────────────────────────
            if _all_failed:
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            if consecutive_errors >= budget.max_consecutive_errors:
                rag_budget_exceeded_total.labels(budget_type="consecutive_errors").inc()
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You have reached the tool response budget for this turn. "
                            "Provide your best answer with the information gathered so far."
                        ),
                    }
                )
                break

            if cumulative_tool_latency >= budget.max_tool_latency_s:
                rag_budget_exceeded_total.labels(budget_type="latency").inc()
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Tool response time budget reached. "
                            "Provide your best answer with the information gathered so far."
                        ),
                    }
                )
                break

            # ── Inject tool results into messages for next iteration ──────────
            # Rerank + build context block for message injection.
            _type_counts = _Counter(item.item_type.value for item in non_none_items)
            _reranked_iter = await p.rerank_items(request.message, non_none_items)
            if non_none_items and _reranked_iter:
                reranked = _reranked_iter
                record_reranker_position_change(non_none_items[0].item_id != reranked[0].item_id)

            _prompt_iter, contradiction_refs, _context_block = p.build_prompt(
                reranked or non_none_items,
                [],
                request.message,
                (),
                intent,
                _type_counts,
            )

            # Inject assistant turn + tool results as user message.
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

            # E-12: increment iteration counter.
            audit.increment_iteration()
            iteration_count += 1

        else:
            # for/else: loop exited by hitting max_iterations (not by break).
            rag_budget_exceeded_total.labels(budget_type="iterations").inc()
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Maximum tool iterations reached. "
                        "Provide your best answer with the information gathered so far."
                    ),
                }
            )

        # Record total iteration count for E-6 metrics.
        rag_agent_iterations.observe(iteration_count)

        # ── Step 6: Final streaming answer (only when tool calls occurred) ────
        # When the LLM answered directly (no tool calls), full_text is already set
        # and we skip this streaming turn.
        if had_tool_calls:
            # Rerank + build final prompt if we haven't done so yet.
            if non_none_items and not reranked:
                _type_counts = _Counter(item.item_type.value for item in non_none_items)
                reranked = await p.rerank_items(request.message, non_none_items)
                if non_none_items and reranked:
                    record_reranker_position_change(non_none_items[0].item_id != reranked[0].item_id)

            try:
                async for chunk in p.llm_chain.stream_chat(
                    messages,
                    max_tokens=budget.max_tokens_final,
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

        # ── E-7: Citation egress scrubbing ────────────────────────────────────
        # Scrub entity/article refs in the answer that were NOT grounded in any
        # tool result. This prevents the LLM from fabricating citation IDs.
        full_text, scrub_count = _scrub_unseen_refs(full_text, seen_item_ids)
        if scrub_count > 0:
            log.warning("citations_scrubbed", count=scrub_count)  # type: ignore[no-any-return]
            rag_citations_scrubbed_total.inc(scrub_count)

        # ── Step 9: Output processing + citations ────────────────────────────────
        answer, citations = p.process_output(full_text, reranked)

        # E-12: stash the final answer on the audit object so execute_streaming's
        # finally block can pass it to finalize(). Using a private attribute to avoid
        # modifying the ChatAuditLogger public interface with a mutable answer field.
        audit._last_answer = answer  # type: ignore[attr-defined]

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
        """Run the full pipeline synchronously — collects all SSE events and returns final answer.

        PLAN-0087 Wave F D-R1-005: error events emitted by ``execute_streaming`` MUST
        propagate to the route handler as exceptions. Previously this method silently
        accumulated only ``token``, ``citations``, ``contradictions`` and ``metadata``
        events — when the LLM first turn failed the user received a 200 OK with an
        empty ``answer`` field instead of a ``5xx``.
        """
        from rag_chat.domain.errors import (
            PromptInjectionError,
            ProviderUnavailableError,
            RateLimitExceededError,
        )

        answer = ""
        citations: list = []
        contradictions: list = []
        metadata: dict = {}  # type: ignore[type-arg]
        error_payload: dict | None = None  # type: ignore[type-arg]

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
            elif event_type == "error" and error_payload is None:
                error_payload = data

        if error_payload is not None:
            code = str(error_payload.get("code", "")).upper()
            message = str(error_payload.get("message", "")) or "Unable to process request"
            log.warning(  # type: ignore[no-any-return]
                "execute_sync_error_event",
                code=code,
                message=message,
            )
            if code == "RATE_LIMIT_EXCEEDED":
                raise RateLimitExceededError(message)
            if code == "INPUT_REJECTED":
                raise PromptInjectionError(message)
            raise ProviderUnavailableError(message)

        # Safety net: strip any residual <think> blocks from accumulated token stream.
        answer = self._pipeline.process_output(answer, [])[0]

        return {
            "answer": answer,
            "citations": citations,
            "contradictions": contradictions,
            **metadata,
        }


def _new_thread_id() -> Any:
    """Generate a new UUIDv7 for thread/message/turn IDs."""
    from common.ids import new_uuid7  # type: ignore[import-untyped]

    return new_uuid7()
