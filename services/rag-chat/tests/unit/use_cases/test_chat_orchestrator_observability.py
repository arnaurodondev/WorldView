"""Unit tests for PLAN-0093 QA-7 observability changes in chat_orchestrator.

Covers six changes that are all in chat_orchestrator.py:

- C1 — ``rag_no_tool_calls_first_turn_total`` counter + ``llm_answered_without_tools`` log.
- C2 — ``rag_tool_result_items`` per-tool histogram.
- C3 — ``tool_selection_resolved`` structured log line.
- C4 — ``tool_slow`` warning when a tool exceeds 2.0s.
- C5 — ``agent_budget_exceeded`` logs at all 3 budget-exit sites.
- C6 — PII redaction at the all-tools-failed log site.

Test design notes:
- Mocks follow the same shape used in ``test_chat_orchestrator_tool_loop.py``
  so we don't drift the orchestrator's test harness contract.
- Structured-log assertions use ``structlog.testing.capture_logs()`` which
  short-circuits the structlog processor chain regardless of how the app
  configured logging (no caplog/handler wiring required).
- Prometheus counter assertions query the singleton metric directly via
  ``.collect()`` — never the global REGISTRY — so the assertions are
  independent of the ``isolated_registry`` monkeypatch in conftest.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers (copy of the harness used in test_chat_orchestrator_tool_loop.py —
# duplicated here so this file is self-contained and the sibling file is
# untouched, satisfying R19 "never delete tests")
# ---------------------------------------------------------------------------


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.content = text  # C1 uses getattr(..., "content", ...) too
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str = "get_price_history", inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"ticker": "AAPL"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_pipeline(
    first_llm_response: Any = None,
    stream_chunks: list[str] | None = None,
) -> MagicMock:
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("test prompt", [], "context block"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(return_value=("Final answer.", []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    default_first_response = first_llm_response or _make_llm_tool_response(text="Direct answer.")
    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.chat_with_tools = AsyncMock(return_value=default_first_response)
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    _chunks = stream_chunks or ["Final ", "answer."]

    async def _stream_chat(messages: list, **kwargs: Any):
        for chunk in _chunks:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    pipeline.emitter = MagicMock()
    pipeline.emitter.emit_status = MagicMock(return_value={"event": "status", "data": "{}"})
    pipeline.emitter.emit_thinking = MagicMock(
        return_value={"event": "thinking", "data": json.dumps({"stage": "tool_classification"})}
    )
    pipeline.emitter.emit_token = MagicMock(side_effect=lambda t: {"event": "token", "data": json.dumps({"text": t})})
    pipeline.emitter.emit_citations = MagicMock(return_value={"event": "citations", "data": "[]"})
    pipeline.emitter.emit_contradictions = MagicMock(return_value={"event": "contradictions", "data": "[]"})
    pipeline.emitter.emit_metadata = MagicMock(return_value={"event": "metadata", "data": "{}"})
    pipeline.emitter.emit_done = MagicMock(return_value={"event": "done", "data": '{"type":"done"}'})
    pipeline.emitter.emit_final_answer = MagicMock(
        side_effect=lambda t: {"event": "final_answer", "data": json.dumps({"text": t})}
    )
    pipeline.emitter.emit_tool_call = MagicMock(
        side_effect=lambda name, inp, **kw: {"event": "tool_call", "data": json.dumps({"tool": name})}
    )
    pipeline.emitter.emit_tool_result = MagicMock(
        side_effect=lambda name, status="ok", item_count=0, **kw: {
            "event": "tool_result",
            "data": json.dumps({"tool": name, "status": status, "item_count": item_count}),
        }
    )
    pipeline.emitter.emit_error = MagicMock(
        side_effect=lambda code, msg: {"event": "error", "data": json.dumps({"code": code, "message": msg})}
    )

    return pipeline


def _make_chat_request(message: str = "What was AAPL's price last quarter?") -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message=message,
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


def _make_tool_executor_mock(return_items: list, tool_defs: list | None = None) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_price_history")
    registry.to_tool_definitions = MagicMock(return_value=tool_defs or [])
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_factory_mock(executor: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


def _make_retrieved_item(text: str = "AAPL price history...") -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:price_history:AAPL"
    item.text = text
    item.score = 0.9
    return item


async def _collect_events_and_logs(orch: Any, request: Any, uow: Any) -> tuple[list, list[dict]]:
    """Run execute_streaming under structlog capture and return (events, log_records)."""
    events: list = []
    with structlog.testing.capture_logs() as cap_logs:
        async for event in orch.execute_streaming(request, uow):
            events.append(event)
    return events, list(cap_logs)


# ---------------------------------------------------------------------------
# C1 — rag_no_tool_calls_first_turn + llm_answered_without_tools
# ---------------------------------------------------------------------------


class TestC1NoToolCallsFirstTurn:
    def test_counter_increments_when_iteration_0_has_no_tool_calls(self) -> None:
        """LLM returns ``tool_calls=[]`` on iter 0 → counter goes up by 1."""
        from rag_chat.application.metrics.prometheus import rag_no_tool_calls_first_turn
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        def _value(provider: str) -> float:
            for m in rag_no_tool_calls_first_turn.collect():
                for s in m.samples:
                    if s.name.endswith("_total") and s.labels.get("provider") == provider:
                        return s.value
            return 0.0

        # First-turn direct answer → triggers the smoke signal.
        first_resp = _make_llm_tool_response(text="AAPL is a tech company.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=first_resp)
        # Use a unique provider name so cross-test counter contamination cannot
        # mask or accidentally pass the assertion.
        pipeline.llm_chain.last_provider_name = "provider_c1_test"

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        before = _value("provider_c1_test")
        asyncio.run(_collect_events_and_logs(orch, request, uow))
        after = _value("provider_c1_test")

        assert after == before + 1.0

    def test_warning_log_emitted_with_expected_fields(self) -> None:
        """structlog capture_logs sees ``llm_answered_without_tools`` with fields."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        first_resp = _make_llm_tool_response(text="Short direct answer.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=first_resp)
        pipeline.llm_chain.last_provider_name = "provider_c1_log"

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        matches = [r for r in logs if r.get("event") == "llm_answered_without_tools"]
        assert matches, f"expected llm_answered_without_tools log, got events: {[r.get('event') for r in logs]}"
        rec = matches[0]
        assert rec["iteration"] == 0
        assert rec["provider"] == "provider_c1_log"
        # Text length is derived from llm_response.content or .text.
        assert rec["text_length"] == len("Short direct answer.")
        assert rec["log_level"] == "warning"

    def test_counter_does_not_increment_when_tools_were_called(self) -> None:
        """When the LLM picks at least one tool on iter 0, counter must NOT advance."""
        from rag_chat.application.metrics.prometheus import rag_no_tool_calls_first_turn
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        def _value(provider: str) -> float:
            for m in rag_no_tool_calls_first_turn.collect():
                for s in m.samples:
                    if s.name.endswith("_total") and s.labels.get("provider") == provider:
                        return s.value
            return 0.0

        tool_block = _make_tool_use_block("get_price_history")
        # First iter has a tool call → C1 should NOT fire even though iter 1 has
        # no tool calls (the spec restricts C1 to iteration_0).
        call_count = [0]

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return _make_llm_tool_response(text="Iter 1 direct answer.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _two_call_llm
        pipeline.llm_chain.last_provider_name = "provider_c1_neg"

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        before = _value("provider_c1_neg")
        asyncio.run(_collect_events_and_logs(orch, request, uow))
        after = _value("provider_c1_neg")
        assert after == before  # not iteration 0


# ---------------------------------------------------------------------------
# C2 — rag_tool_result_items histogram
# ---------------------------------------------------------------------------


class TestC2ToolResultItemsHistogram:
    def test_histogram_records_zero_for_failed_tool(self) -> None:
        """A tool returning None → an observation of 0 in the tool's histogram."""
        from rag_chat.application.metrics.prometheus import rag_tool_result_items
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        def _count(tool_name: str) -> float:
            total = 0.0
            for m in rag_tool_result_items.collect():
                for s in m.samples:
                    if s.name.endswith("_count") and s.labels.get("tool_name") == tool_name:
                        total += s.value
            return total

        tool_block = _make_tool_use_block("c2_zero_tool")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # All-fail on iter 0 routes through the ``all_tools_failed`` early-return
        # branch (fallback chain returns empty for an unregistered tool name).
        # That branch fires AFTER the per-tool histogram observation, which is
        # exactly what we want: exactly one observation of 0.
        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        before = _count("c2_zero_tool")
        asyncio.run(_collect_events_and_logs(orch, request, uow))
        after = _count("c2_zero_tool")
        # Exactly one observation recorded (count=0 still adds 1 to the histogram count).
        assert after == before + 1

    def test_histogram_records_n_items_for_successful_tool(self) -> None:
        """A tool returning N items → ``_sum`` advances by N and ``_count`` by 1."""
        from rag_chat.application.metrics.prometheus import rag_tool_result_items
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        def _sum_and_count(tool_name: str) -> tuple[float, float]:
            _s = 0.0
            _c = 0.0
            for m in rag_tool_result_items.collect():
                for samp in m.samples:
                    if samp.labels.get("tool_name") != tool_name:
                        continue
                    if samp.name.endswith("_sum"):
                        _s += samp.value
                    elif samp.name.endswith("_count"):
                        _c += samp.value
            return _s, _c

        tool_block = _make_tool_use_block("c2_n_tool")
        # 20 items inside a single list result → flat _count==20 for this tool call.
        items = [_make_retrieved_item() for _ in range(20)]

        # Two-turn LLM: iter 0 picks the tool, iter 1 answers directly (stopping
        # the agent loop after a single observation). Without this the AsyncMock
        # would replay tool_calls every iteration and we'd accumulate up to
        # ``max_iterations`` histogram observations for the same tool_name.
        call_count = [0]

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return _make_llm_tool_response(text="Done.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _two_call_llm
        executor = _make_tool_executor_mock([items])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        sum_before, count_before = _sum_and_count("c2_n_tool")
        asyncio.run(_collect_events_and_logs(orch, request, uow))
        sum_after, count_after = _sum_and_count("c2_n_tool")

        assert count_after == count_before + 1
        assert sum_after == sum_before + 20.0

    def test_dedup_cache_hit_does_not_double_observe_tool_result_items(self) -> None:
        """If the same tool call is requested twice (second turn hits the dedup cache),
        rag_tool_result_items must be observed exactly once per logical tool invocation
        (once on the fresh call, once on the cache-hit re-emit), not double-counted."""
        from rag_chat.application.metrics.prometheus import rag_tool_result_items
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        def _count(tool_name: str) -> float:
            total = 0.0
            for m in rag_tool_result_items.collect():
                for s in m.samples:
                    if s.name.endswith("_count") and s.labels.get("tool_name") == tool_name:
                        total += s.value
            return total

        # WHY: the orchestrator dedup cache stores results after the first execute_all.
        # On a second LLM turn requesting the same tool, the cache entry is replayed
        # directly without calling execute_all again.  Both turns emit a tool_result
        # event and record rag_tool_result_items — so over 2 turns we expect count==2
        # (one observation per call site, not zero or four from double-counting).
        #
        # Chat-latency lever B (2026-07-19) added an all-cached early-stop: a hop
        # requesting ONLY already-answered tools breaks the loop. To keep the
        # dedup-replay path under test (rather than tripping the early-stop),
        # iter 1 requests a MIXED batch — the same tool (cache hit → replay) PLUS
        # a fresh tool — so at least one call is fresh and the loop proceeds.
        tool_block = _make_tool_use_block("c2_dedup_tool", inp={"ticker": "AAPL"})
        fresh_block = _make_tool_use_block("c2_fresh_tool", inp={"ticker": "MSFT"})
        items = [_make_retrieved_item()]
        call_count = [0]

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Iter 0: the tracked tool runs fresh and is cached.
                return _make_llm_tool_response(tool_calls=[tool_block])
            if call_count[0] == 2:
                # Iter 1: MIXED batch — tracked tool is a cache-hit replay,
                # c2_fresh_tool is genuinely fresh (prevents the early-stop).
                return _make_llm_tool_response(tool_calls=[tool_block, fresh_block])
            # Iter 2: direct answer stops the loop.
            return _make_llm_tool_response(text="Done.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _two_call_llm
        executor = _make_tool_executor_mock([items])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        before = _count("c2_dedup_tool")
        asyncio.run(_collect_events_and_logs(orch, request, uow))
        after = _count("c2_dedup_tool")

        # Exactly 2 observations (one per tool_result emit, not 4 from double-counting).
        assert after == before + 2, f"expected 2 observations for dedup tool, got {after - before}"


# ---------------------------------------------------------------------------
# C3 — tool_selection_resolved structured log
# ---------------------------------------------------------------------------


class TestC3ToolSelectionResolved:
    def test_log_emitted_with_tool_name_list(self) -> None:
        """The log line carries iteration, tools, n_calls, provider — NO args."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block_a = _make_tool_use_block("get_price_history", inp={"ticker": "secret_ticker_AAPL"})
        tool_block_b = _make_tool_use_block("search_documents", inp={"query": "sensitive search text"})
        first_resp = _make_llm_tool_response(tool_calls=[tool_block_a, tool_block_b])
        pipeline = _make_pipeline(first_llm_response=first_resp)
        pipeline.llm_chain.last_provider_name = "provider_c3"

        executor = _make_tool_executor_mock([_make_retrieved_item(), _make_retrieved_item()])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        matches = [r for r in logs if r.get("event") == "tool_selection_resolved"]
        assert matches, f"expected tool_selection_resolved log, got: {[r.get('event') for r in logs]}"
        rec = matches[0]
        assert rec["tools"] == ["get_price_history", "search_documents"]
        assert rec["n_calls"] == 2
        assert rec["iteration"] == 0
        assert rec["provider"] == "provider_c3"

        # SECURITY: no tool args + no user message must appear in any
        # structured field of the tool_selection_resolved record.
        as_str = json.dumps({k: str(v) for k, v in rec.items() if k != "event"})
        assert "secret_ticker_AAPL" not in as_str
        assert "sensitive search text" not in as_str


# ---------------------------------------------------------------------------
# C4 — tool_slow warning
# ---------------------------------------------------------------------------


class TestC4ToolSlowWarning:
    def test_warning_emitted_when_tool_takes_over_2s(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A simulated >2.0s tool execution emits ``tool_slow``."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("c4_slow_tool")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        # Drive ``time.monotonic`` to simulate a slow tool call without sleeping.
        #
        # Strategy: return ``call_number * 3.0`` on every call.  Any two
        # adjacent calls produce a diff of 3.0s, which is above the 2.0s
        # threshold.  This makes ``_tool_latency`` large regardless of how
        # many other monotonic() consumers precede ``_tool_t0`` (e.g.
        # ChatAuditLogger.__init__, iter_turn_start, the first-turn latency
        # histogram's finally-block).  Subsequent dedup-hit iterations never
        # call execute_all, so their ``_tool_latency`` is 0.0 and tool_slow
        # doesn't spuriously re-fire.
        _call_count = {"n": 0}

        def _fake_monotonic() -> float:
            _call_count["n"] += 1
            return _call_count["n"] * 3.0

        monkeypatch.setattr(time, "monotonic", _fake_monotonic)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        slow = [r for r in logs if r.get("event") == "tool_slow"]
        assert slow, f"expected tool_slow log, got: {[r.get('event') for r in logs]}"
        rec = slow[0]
        assert rec["tool"] == "c4_slow_tool"
        assert rec["threshold_ms"] == 2000
        assert rec["latency_ms"] >= 2000

    def test_warning_not_emitted_for_fast_tool(self) -> None:
        """A normal (fast) tool call must NOT trigger ``tool_slow``."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("c4_fast_tool")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        slow = [r for r in logs if r.get("event") == "tool_slow"]
        assert not slow, f"unexpected tool_slow log: {slow!r}"


# ---------------------------------------------------------------------------
# C5 — agent_budget_exceeded log at each of the 3 budget-exit sites
# ---------------------------------------------------------------------------


class TestC5BudgetExceededLogs:
    def test_consecutive_errors_budget_logs_event(self) -> None:
        """A ok-then-fail-fail sequence trips ``budget_type=consecutive_errors``.

        Iteration 0 routes all-fail cases through the ``all_tools_failed`` return
        branch (covered by C6), so to actually reach the consecutive_errors
        site we need at least one successful round followed by enough failures.
        We also vary the tool name each iteration so the dedup cache doesn't
        replay stale results and accidentally suppress the failure counter.
        """
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        ok_item = _make_retrieved_item()
        results_seq = [[ok_item], [None], [None]]
        call_idx = [0]

        async def _seq_execute_all(tool_calls):
            r = results_seq[min(call_idx[0], len(results_seq) - 1)]
            call_idx[0] += 1
            return r

        executor = _make_tool_executor_mock([])
        executor.execute_all = _seq_execute_all
        factory = _make_factory_mock(executor)
        pipeline = _make_pipeline()

        async def _always_tools(messages, tools=None, **kwargs):
            return _make_llm_tool_response(tool_calls=[_make_tool_use_block(f"tool_iter_{call_idx[0]}")])

        pipeline.llm_chain.chat_with_tools = _always_tools
        budget = AgentBudget(max_iterations=8, max_consecutive_errors=2)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)

        _events, logs = asyncio.run(_collect_events_and_logs(orch, _make_chat_request(), MagicMock()))
        matches = [
            r
            for r in logs
            if r.get("event") == "agent_budget_exceeded" and r.get("budget_type") == "consecutive_errors"
        ]
        assert matches, f"expected consecutive_errors log, got: {[r.get('event') for r in logs]}"

    def test_latency_budget_logs_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cumulative tool latency above the threshold logs ``budget_type=latency``."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        # Each tool round measures ~100s elapsed via monkeypatched monotonic.
        # Returning many ticks via a counter keeps the sequence stable even
        # when the orchestrator calls monotonic() a few extra times.
        counter = {"v": 0.0}

        def _fake_monotonic() -> float:
            counter["v"] += 50.0  # each call advances 50s
            return counter["v"]

        monkeypatch.setattr(time, "monotonic", _fake_monotonic)

        # LLM keeps requesting tools (different name per iter to defeat dedup).
        seq = {"i": 0}

        async def _always_tools(messages, tools=None, **kwargs):
            seq["i"] += 1
            return _make_llm_tool_response(tool_calls=[_make_tool_use_block(f"latency_tool_{seq['i']}")])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _always_tools

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        # Set max_tool_latency_s tiny so the very first observed delta blows the budget.
        budget = AgentBudget(max_iterations=8, max_tool_latency_s=0.1)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        matches = [r for r in logs if r.get("event") == "agent_budget_exceeded" and r.get("budget_type") == "latency"]
        assert matches, f"expected latency agent_budget_exceeded log, got events: {[r.get('event') for r in logs]}"

    def test_iterations_budget_logs_event(self) -> None:
        """Hitting max_iterations fires the for/else branch with budget_type=iterations."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        seq = {"i": 0}

        async def _always_tools(messages, tools=None, **kwargs):
            seq["i"] += 1
            return _make_llm_tool_response(tool_calls=[_make_tool_use_block(f"iter_tool_{seq['i']}")])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _always_tools

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        # Generous error/latency budgets — only max_iterations should trigger.
        budget = AgentBudget(max_iterations=2, max_consecutive_errors=10, max_tool_latency_s=1000.0)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        matches = [
            r for r in logs if r.get("event") == "agent_budget_exceeded" and r.get("budget_type") == "iterations"
        ]
        assert matches, f"expected iterations agent_budget_exceeded log, got events: {[r.get('event') for r in logs]}"

    def test_happy_path_completion_does_not_emit_budget_exceeded(self) -> None:
        """When the agent completes normally (tool on iter 0, direct answer on iter 1),
        agent_budget_exceeded must NOT fire regardless of which budget type would
        theoretically apply — the loop exits cleanly via the direct-answer branch."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("happy_path_tool")
        call_count = [0]

        async def _normal_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Iter 0: LLM picks a tool.
                return _make_llm_tool_response(tool_calls=[tool_block])
            # Iter 1: LLM answers directly — clean loop exit.
            return _make_llm_tool_response(text="Here is your answer.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _normal_llm

        executor = _make_tool_executor_mock([_make_retrieved_item()])
        factory = _make_factory_mock(executor)

        # Generous budgets — no budget should be tripped on a normal 2-turn exchange.
        budget = AgentBudget(max_iterations=8, max_consecutive_errors=5, max_tool_latency_s=1000.0)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        budget_logs = [r for r in logs if r.get("event") == "agent_budget_exceeded"]
        assert not budget_logs, f"agent_budget_exceeded must NOT fire on happy path, got: {budget_logs!r}"


# ---------------------------------------------------------------------------
# C6 — PII redaction at all_tools_failed
# ---------------------------------------------------------------------------


class TestC6PiiRedaction:
    def test_sensitive_query_is_hashed_not_logged_verbatim(self) -> None:
        """Verbatim ``query`` is gone; ``query_hash`` + ``query_length`` + ``query_first_word`` replace it."""
        import hashlib

        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        sensitive = "this is sensitive content with portfolio details"

        tool_block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # All tools fail → iteration-0 all_tools_failed branch fires (no fallback
        # registered for ``get_price_history``).
        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request(message=sensitive)
        uow = MagicMock()

        _events, logs = asyncio.run(_collect_events_and_logs(orch, request, uow))
        matches = [r for r in logs if r.get("event") == "all_tools_failed"]
        assert matches, f"expected all_tools_failed log, got events: {[r.get('event') for r in logs]}"
        rec = matches[0]

        # Hash matches the deterministic SHA-256 prefix.
        expected_hash = hashlib.sha256(sensitive.encode("utf-8")).hexdigest()[:12]
        assert rec["query_hash"] == expected_hash
        assert len(rec["query_hash"]) == 12
        assert rec["query_length"] == len(sensitive)
        assert rec["query_first_word"] == "this"

        # Verbatim sensitive substring must not be present in any structured field.
        as_str = json.dumps({k: str(v) for k, v in rec.items()})
        assert "portfolio details" not in as_str
        # And the legacy ``query`` key must be gone.
        assert "query" not in rec or rec.get("query") is None
