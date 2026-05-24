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


# ── FIX-LIVE-E: Multi-tool fallback chain (F-LIVE-005C-FALLBACK) ─────────────
#
# WHY: Phase 5c Q2 ("Show me the latest news on MSTR — what should I know?")
# verdict USELESS with error all_tools_failed.  The agent called
# search_documents() which returned empty, then the all-tools-failed guard
# fired without trying any alternative tool.  This module-level fallback table
# gives the orchestrator a structured way to try semantically-equivalent tools
# when the primary tool returns empty results on iteration 0.
#
# Two tables work in tandem:
#   _FALLBACK_MAP            — ordered list of alt tools to try, by failed tool
#   _FALLBACK_ARG_PROJECTIONS — per (failed_tool, alt_tool) arg shaper
#
# The projection function takes the failed-call args + an optional EntityContext
# and returns valid args for the alt tool.  Returning None means "we cannot
# build valid args for this alt tool" (e.g. no entity_id available) and the
# orchestrator should move to the next alt in the chain.
#
# Pre-FIX-LIVE-E behavior: alt_args = dict(failed.input) verbatim, which raised
# TypeError inside the handler's **args call when the alt tool's signature did
# not accept the failed tool's keys.  ToolExecutor silently swallowed it as
# "tool returned None".  See FIX-LIVE-E in
# docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md.

_FALLBACK_MAP: dict[str, list[str]] = {
    # search_documents → relaxed-filter retry → claims → intelligence bundle
    # WHY this order: cheapest first (same tool, looser filters), then claims
    # (analyst-curated, narrower scope), then full intelligence bundle (heaviest
    # S7Intel call but always returns SOMETHING for a known entity).
    "search_documents": ["search_documents", "search_claims", "get_entity_intelligence"],
}


def _project_relaxed_search_documents(
    failed_args: dict[str, Any],
    ctx: Any,  # EntityContext | None  (avoid circular TYPE_CHECKING import at runtime)
) -> dict[str, Any] | None:
    """Identity-shape retry: same tool, drop source_types, widen window by 90d.

    WHY widen: the most common reason search_documents returns empty for a
    narrow date_from/date_to window is publication lag — a 90-day pad usually
    recovers something.  We deliberately KEEP date filters (relaxed) so the
    LLM still understands the result is approximately what it asked for.
    """
    out = {k: v for k, v in failed_args.items() if k != "source_types"}

    # Best-effort date widening — only when both bounds are ISO strings.
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    df_raw = out.get("date_from")
    dt_raw = out.get("date_to")
    if isinstance(df_raw, str) and isinstance(dt_raw, str):
        try:
            df = _dt.fromisoformat(df_raw) - _td(days=90)
            dt = _dt.fromisoformat(dt_raw) + _td(days=90)
            out["date_from"] = df.date().isoformat()
            out["date_to"] = dt.date().isoformat()
        except ValueError:
            # Leave dates untouched if parse fails; the retry is still useful.
            pass
    return out


def _project_search_documents_to_search_claims(
    failed_args: dict[str, Any],
    ctx: Any,  # EntityContext | None
) -> dict[str, Any] | None:
    """search_documents → search_claims: keep entity scope, drop date/source filters.

    search_claims requires ``entity_name``.  We use the EntityContext name when
    available (entity-first queries always have ctx); otherwise pull the first
    ticker from entity_tickers as a best-effort name.
    """
    entity_name: str | None = None
    if ctx is not None and getattr(ctx, "name", None):
        entity_name = ctx.name
    else:
        tickers = failed_args.get("entity_tickers") or []
        if isinstance(tickers, list) and tickers:
            entity_name = str(tickers[0])
    if not entity_name:
        return None
    return {"entity_name": entity_name}


def _project_search_documents_to_entity_intelligence(
    failed_args: dict[str, Any],  # (unused; signature kept uniform)
    ctx: Any,  # EntityContext | None
) -> dict[str, Any] | None:
    """search_documents → get_entity_intelligence: needs entity_id from ctx only.

    Returns None when there is no EntityContext (e.g. open-domain question with
    no entity resolved) because we have no UUID to look up.
    """
    if ctx is None or getattr(ctx, "entity_id", None) is None:
        return None
    return {"entity_id": str(ctx.entity_id)}


# Keyed by (failed_tool, alt_tool).  Default behaviour (when a pair is absent)
# is to copy args verbatim — this preserves backward compatibility with any
# alt tool whose signature happens to match the failed tool's.
_FALLBACK_ARG_PROJECTIONS: dict[tuple[str, str], Any] = {
    ("search_documents", "search_documents"): _project_relaxed_search_documents,
    ("search_documents", "search_claims"): _project_search_documents_to_search_claims,
    ("search_documents", "get_entity_intelligence"): _project_search_documents_to_entity_intelligence,
}


def _build_fallback_args(
    failed_tool: str,
    alt_tool: str,
    failed_args: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Return projected args for (failed_tool → alt_tool), or None if not buildable."""
    projector = _FALLBACK_ARG_PROJECTIONS.get((failed_tool, alt_tool))
    if projector is None:
        # No projection registered — copy verbatim (legacy/default behavior).
        return dict(failed_args)
    return projector(failed_args, ctx)  # type: ignore[no-any-return]


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

        system_prompt = (
            tool_executor._registry.to_system_prompt_section()
            + f"\n\nYou are a market intelligence assistant with access to the tools listed above. "
            f"Today's date is {_today}. When you call tools that take dates "
            f"(price history, earnings calendar, economic events, news search), use this "
            f"date as the reference point — never use dates from your pre-training cutoff. "
            f"Use the tools to retrieve precise data before answering. "
            f"If a tool returns no data, acknowledge that in your answer. "
            f"For well-known entity relationships where tools return sparse results, you may supplement "
            f"from your training knowledge but must label it 'Based on public knowledge: …' without "
            f"inventing any KG-specific metadata.\n\n"
            f"CITATIONS: when the tools you call return documents, articles, or chunks "
            f"with identifiers, cite them inline using [N1], [N2], … markers — one marker "
            f"per claim that is supported by a retrieved item, in the order the items "
            f"appear in the tool output. Do NOT invent citation numbers. If no documents "
            f"were retrieved, do not emit any citation markers." + _entity_map_section
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "")
            if role is not None:
                messages.append({"role": getattr(role, "value", str(role)), "content": content})
        messages.append({"role": "user", "content": request.message})

        # ── E-6: Multi-turn agent loop state ──────────────────────────────────
        non_none_items: list[RetrievedItem] = []
        reranked: list[RetrievedItem] = []
        contradiction_refs: list = []
        intent = QueryIntent.GENERAL
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
            #
            # FIX-LIVE-E (2026-05-24): before surrendering, try the multi-tool
            # fallback chain.  For each failed tool with a registered
            # _FALLBACK_MAP entry, walk the alt tools in order, project the args
            # via _build_fallback_args, and invoke them via the same executor.
            # SSE events are emitted with is_fallback=true so the UI/operator
            # can see the retry visibly.  Cite F-LIVE-005C-FALLBACK.
            if iteration == 0 and _all_failed and not _action_pending_items:
                _fallback_events: list[dict[str, str]] = []
                _fallback_items = await self._run_fallback_chain(
                    tool_calls=tool_calls,
                    tool_items=tool_items,
                    tool_executor=tool_executor,
                    emitter=p.emitter,
                    audit=audit,
                    entity_context=entity_context,
                    sse_events_out=_fallback_events,
                )
                # Yield any SSE events the fallback chain produced (tool_call,
                # tool_result).  Doing this after the await keeps the helper
                # synchronous-in-effect for the orchestrator caller.
                for _ev in _fallback_events:
                    yield _ev

                # If fallback recovered ANY items, reset _all_failed + append to
                # the accumulated pool and continue the loop normally — the LLM
                # will see the data on its next turn.
                if _fallback_items:
                    _all_failed = False
                    non_none_items.extend(_fallback_items)
                    # Harvest IDs from fallback items for E-7 citation allowlist.
                    for _it in _fallback_items:
                        _raw_id = getattr(_it, "item_id", None)
                        if _raw_id:
                            seen_item_ids.add(str(_raw_id).lower())
                        _src_id = getattr(_it, "source_id", None)
                        if _src_id:
                            seen_item_ids.add(str(_src_id).lower())
                else:
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

    async def _run_fallback_chain(
        self,
        *,
        tool_calls: list[ToolUseBlock],
        tool_items: list[Any],
        tool_executor: Any,
        emitter: Any,
        audit: Any,
        entity_context: Any,
        sse_events_out: list[dict[str, str]],
    ) -> list[RetrievedItem]:
        """FIX-LIVE-E: Try multi-tool fallback chain for each failed primary tool.

        For each ``tool_calls[i]`` whose ``tool_items[i]`` returned empty/None,
        walk the registered alt chain from ``_FALLBACK_MAP``, project args via
        ``_build_fallback_args``, and invoke the alt via ``tool_executor.execute``.
        Stop at the first alt that returns items.

        SSE events (tool_call with ``is_fallback=true``, then tool_result) are
        appended to ``sse_events_out`` so the orchestrator can yield them in
        order after this coroutine returns.

        Args:
            tool_calls:      LLM-emitted primary tool calls (parallel to tool_items).
            tool_items:      Per-call results (None / [] / list[RetrievedItem]).
            tool_executor:   Per-request ToolExecutor (already auth-scoped).
            emitter:         SSE emitter (pipeline.emitter).
            audit:           ChatAuditLogger for E-12 tool-call recording.
            entity_context:  EntityContext | None for arg-projection.
            sse_events_out:  Mutable list — events appended in emission order.

        Returns:
            Flat list of RetrievedItems recovered across all fallback attempts.
        """
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        recovered: list[RetrievedItem] = []

        for tc, item in zip(tool_calls, tool_items, strict=False):
            _count = len(item) if isinstance(item, list) else (1 if item is not None else 0)
            if _count > 0:
                continue  # primary tool succeeded — no fallback needed

            alt_chain = _FALLBACK_MAP.get(tc.name) or []
            if not alt_chain:
                continue  # no fallback registered for this tool

            for alt_name in alt_chain:
                # Skip the trivial identity case: only allow same-tool re-invocation
                # when an explicit projection (e.g. relaxed-filter retry) is registered.
                if alt_name == tc.name and (tc.name, alt_name) not in _FALLBACK_ARG_PROJECTIONS:
                    continue

                projected = _build_fallback_args(tc.name, alt_name, tc.input, entity_context)
                if projected is None:
                    log.warning(  # type: ignore[no-any-return]
                        "tool_fallback_no_valid_args",
                        failed_tool=tc.name,
                        alt_tool=alt_name,
                    )
                    continue

                # Emit SSE tool_call (is_fallback=true) so the UI shows the retry.
                _safe_input = {k: v for k, v in projected.items() if k not in {"query", "text"}}
                sse_events_out.append(
                    emitter.emit_tool_call(
                        alt_name,
                        _safe_input,
                        is_fallback=True,
                        fallback_of=tc.name,
                    )
                )

                _alt_block = ToolUseBlock(name=alt_name, input=projected, tool_use_id=f"fallback_{alt_name}")
                _alt_result = await tool_executor.execute(_alt_block)
                _alt_count = (
                    len(_alt_result) if isinstance(_alt_result, list) else (1 if _alt_result is not None else 0)
                )
                _alt_status = "ok" if _alt_count > 0 else ("empty" if _alt_result is not None else "error")

                sse_events_out.append(emitter.emit_tool_result(alt_name, status=_alt_status, item_count=_alt_count))

                # Record on audit log so /chat_audit_log captures the retry.
                audit.record_tool_call(alt_name, success=_alt_count > 0, latency_ms=0)

                if _alt_count > 0:
                    log.info(  # type: ignore[no-any-return]
                        "tool_fallback_succeeded",
                        failed_tool=tc.name,
                        alt_tool=alt_name,
                        item_count=_alt_count,
                    )
                    if isinstance(_alt_result, list):
                        recovered.extend(_alt_result)
                    else:
                        recovered.append(_alt_result)
                    break  # first hit wins; move on to next failed primary tool

        return recovered

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
