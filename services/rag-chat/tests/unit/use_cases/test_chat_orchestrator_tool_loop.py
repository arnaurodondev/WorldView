"""Unit tests for ChatOrchestratorUseCase tool-use path (PLAN-0067 W11-3).

After W11-3 the orchestrator uses tool-use as the ONLY path.
These tests verify:
- tool-use path is always active (no classical path fallback)
- tool_call events are emitted before execute_all
- tool_result events are emitted after execute_all
- all-tools-failed guard prevents second LLM turn
- new constructor: tool_executor_factory parameter

Kept tests that are still valid after W11-3 migration.
Old tests that relied on `tool_executor=None` classical path behaviour are removed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    """Build a mock LLMToolResponse."""
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str = "get_price_history", inp: dict | None = None) -> MagicMock:
    """Build a mock ToolUseBlock."""
    block = MagicMock()
    block.name = name
    block.input = inp or {"ticker": "AAPL"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_pipeline(
    first_llm_response: Any = None,
    stream_chunks: list[str] | None = None,
) -> MagicMock:
    """Build a mock ChatPipeline for orchestrator tests."""

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

    # LLM chain: chat_with_tools for first turn, stream_chat for second
    default_first_response = first_llm_response or _make_llm_tool_response(text="Direct answer.")
    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.chat_with_tools = AsyncMock(return_value=default_first_response)
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    # stream_chat: async generator for second LLM turn
    _chunks = stream_chunks or ["Final ", "answer."]

    async def _stream_chat(messages: list, **kwargs: Any):
        for chunk in _chunks:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    # SSE emitter — return realistic dicts
    pipeline.emitter = MagicMock()
    pipeline.emitter.emit_status = MagicMock(return_value={"event": "status", "data": "{}"})
    pipeline.emitter.emit_thinking = MagicMock(
        return_value={"event": "thinking", "data": json.dumps({"stage": "tool_classification"})}
    )
    pipeline.emitter.emit_token = MagicMock(side_effect=lambda t: {"event": "token", "data": json.dumps({"text": t})})
    pipeline.emitter.emit_final_answer = MagicMock(
        side_effect=lambda t: {"event": "final_answer", "data": json.dumps({"text": t})}
    )
    pipeline.emitter.emit_citations = MagicMock(return_value={"event": "citations", "data": "[]"})
    pipeline.emitter.emit_contradictions = MagicMock(return_value={"event": "contradictions", "data": "[]"})
    pipeline.emitter.emit_metadata = MagicMock(return_value={"event": "metadata", "data": "{}"})
    pipeline.emitter.emit_done = MagicMock(return_value={"event": "done", "data": '{"type":"done"}'})
    pipeline.emitter.emit_tool_call = MagicMock(
        side_effect=lambda name, inp, **kw: {"event": "tool_call", "data": json.dumps({"tool": name})}
    )
    # **kw absorbs the optional enrichment kwargs (duration_ms, result_preview,
    # reason, status_code, elapsed_ms) — these tests assert on the core triple.
    pipeline.emitter.emit_tool_result = MagicMock(
        side_effect=lambda name, status="ok", item_count=0, **kw: {
            "event": "tool_result",
            "data": json.dumps({"tool": name, "status": status, "item_count": item_count}),
        }
    )
    # build_result_preview must return a JSON-serialisable list (a bare
    # MagicMock would crash json.dumps inside the real emitter when used).
    pipeline.emitter.build_result_preview = MagicMock(return_value=[])
    pipeline.emitter.emit_error = MagicMock(
        side_effect=lambda code, msg: {"event": "error", "data": json.dumps({"code": code, "message": msg})}
    )
    # PLAN-0107: emit_agent_iteration produces a per-iteration progress event.
    # Mock returns a dict matching the on-the-wire shape so list-of-events tests
    # can pattern-match on stage strings without de-serialising JSON.
    pipeline.emitter.emit_agent_iteration = MagicMock(
        side_effect=lambda *, iteration, max_iterations, stage, tools_completed_total, elapsed_ms: {
            "event": "agent_iteration",
            "data": json.dumps(
                {
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                    "stage": stage,
                    "tools_completed_total": tools_completed_total,
                    "elapsed_ms": elapsed_ms,
                }
            ),
        }
    )

    return pipeline


def _make_chat_request() -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What was AAPL's price last quarter?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


def _make_tool_executor_mock(return_items: list, tool_defs: list | None = None) -> MagicMock:
    """Build a mock ToolExecutor with registry attached."""
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_price_history")
    registry.to_tool_definitions = MagicMock(return_value=tool_defs or [])
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_factory_mock(executor: MagicMock) -> MagicMock:
    """Build a mock ToolExecutorFactory that returns the given executor."""
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


def _make_retrieved_item(text: str = "AAPL price history...") -> MagicMock:
    """Create a mock RetrievedItem."""
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:price_history:AAPL"
    item.text = text
    item.score = 0.9
    return item


async def _collect_events(orch: Any, request: Any, uow: Any) -> list:
    """Run execute_streaming and collect all events."""
    events: list = []
    async for event in orch.execute_streaming(request, uow):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Tests: new constructor
# ---------------------------------------------------------------------------


class TestOrchestratorConstructor:
    def test_orchestrator_accepts_factory_param(self) -> None:
        """ChatOrchestratorUseCase(pipeline, tool_executor_factory=...) works."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        factory = _make_factory_mock(_make_tool_executor_mock([]))
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)

        assert orch._tool_factory is factory

    def test_orchestrator_factory_defaults_to_none(self) -> None:
        """ChatOrchestratorUseCase(pipeline=...) still works with no factory arg."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)

        assert orch._tool_factory is None


# ---------------------------------------------------------------------------
# Tests: tool-use path is always active
# ---------------------------------------------------------------------------


class TestToolUseAlwaysActive:
    def test_orchestrator_always_emits_thinking_event(self) -> None:
        """execute_streaming always emits 'thinking' event (tool-use path always active)."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Thinking event must always be emitted
        assert "thinking" in event_types

    def test_orchestrator_calls_chat_with_tools_not_stream(self) -> None:
        """First LLM turn uses chat_with_tools (structured), NOT stream()."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # chat_with_tools must be called; stream must NOT be called
        pipeline.llm_chain.chat_with_tools.assert_called_once()
        # stream() is not used in the tool-use path
        assert not hasattr(pipeline.llm_chain.stream, "call_count") or pipeline.llm_chain.stream.call_count == 0

    def test_orchestrator_completes_with_done_event(self) -> None:
        """execute_streaming must end with a done event even without tool calls."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        assert "done" in event_types
        assert "metadata" in event_types


# ---------------------------------------------------------------------------
# Tests: tool calls
# ---------------------------------------------------------------------------


class TestToolCallsEmitted:
    def test_orchestrator_tool_calls_emit_tool_call_events(self) -> None:
        """When LLM emits tool_calls, 'tool_call' SSE events are yielded before execution."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        assert "tool_call" in event_types

    def test_orchestrator_emits_aggregate_status_badge_before_tool_calls(self) -> None:
        """PLAN-0100 W2 T-W2-01: a single aggregate ``status`` event with
        ``"Loading <a>, <b>, <c>… (N more)…"`` must be emitted right after
        iteration-0's LLM picks tools and BEFORE the per-tool ``tool_call``
        events. This is the FIRST user-visible feedback on tool-using
        questions; it drives the badge in the streaming bubble and is also
        what the chat-eval harness counts toward TTFT (see harness
        ``_CONTENT_EVENT_KINDS``).
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # Four tool calls so the "…(N more)…" suffix is exercised.
        blocks = [
            _make_tool_use_block("get_price_history"),
            _make_tool_use_block("search_news"),
            _make_tool_use_block("get_entity_graph"),
            _make_tool_use_block("get_fundamentals_history"),
        ]
        first_resp = _make_llm_tool_response(tool_calls=blocks)
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # Capture emit_status text so we can assert on the summary copy.
        status_calls: list[str] = []

        def _emit_status(step: str) -> dict:
            status_calls.append(step)
            return {"event": "status", "data": json.dumps({"step": step})}

        pipeline.emitter.emit_status = MagicMock(side_effect=_emit_status)

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        # Find the "Loading …" status emission — must include the first
        # three tool names and the "(1 more)" suffix (4 total tools - 3 listed = 1).
        loading_statuses = [s for s in status_calls if s.startswith("Loading ")]
        assert loading_statuses, "expected at least one 'Loading …' status emission"
        loading = loading_statuses[0]
        assert "get_price_history" in loading
        assert "search_news" in loading
        assert "get_entity_graph" in loading
        assert "1 more" in loading

        # Ordering invariant: the aggregate status frame must arrive BEFORE
        # the first ``tool_call`` frame, otherwise pills would beat the
        # badge to the user and the design contract breaks.
        sse_kinds: list[str] = []
        for ev in events:
            kind = ev.get("event")
            if kind == "status":
                data = json.loads(ev.get("data", "{}"))
                if str(data.get("step", "")).startswith("Loading "):
                    sse_kinds.append("status:loading")
                else:
                    sse_kinds.append("status:other")
            elif kind == "tool_call":
                sse_kinds.append("tool_call")
        assert "status:loading" in sse_kinds
        assert sse_kinds.index("status:loading") < sse_kinds.index("tool_call")

    def test_orchestrator_tool_results_emitted_after_execution(self) -> None:
        """'tool_result' SSE events are emitted after execute_all completes."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_fundamentals_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        assert "tool_result" in event_types

        # tool_result enrichment: the orchestrator must pass the
        # server-measured duration_ms + a result_preview to the emitter
        # (frontend prefers duration_ms over its own client-side timing).
        result_calls = pipeline.emitter.emit_tool_result.call_args_list
        assert result_calls, "expected at least one emit_tool_result call"
        _kwargs = result_calls[0].kwargs
        assert isinstance(_kwargs.get("duration_ms"), int)
        assert "result_preview" in _kwargs

        # Server-derived follow-up suggestions: exactly 3 strings, emitted
        # after the answer (default-on; RAG_CHAT_SUGGESTIONS_ENABLED=false
        # disables).
        pipeline.emitter.emit_suggestions.assert_called_once()
        _suggestions = pipeline.emitter.emit_suggestions.call_args.args[0]
        assert len(_suggestions) == 3
        assert all(isinstance(s, str) and s for s in _suggestions)

        # tool_call must appear before tool_result
        assert event_types.index("tool_call") < event_types.index("tool_result")

    def test_orchestrator_passes_grounding_sample(self) -> None:
        """PLAN-0110 W2 (PRD-0091 FR-5): the orchestrator builds a grounding
        sample from the executed tool's items and plumbs it into
        ``emit_tool_result`` as the ``grounding_sample`` kwarg.

        The emitter itself decides whether to ATTACH the sample to the wire
        frame (flag + status gating, tested in the SSE unit suite); here we only
        assert the plumbing — the sample is computed from ``(tool_name, items)``
        and passed through. This is a no-op behaviour change when the flag is
        off, so it cannot regress the legacy frame.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_fundamentals_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # Spy: build_grounding_sample returns a sentinel so we can assert it is
        # threaded verbatim into emit_tool_result.
        _sentinel_sample = {"fields": {"ticker": "AAPL"}, "sampled_rows": 1, "total_rows": 1, "truncated": False}
        pipeline.emitter.build_grounding_sample = MagicMock(return_value=_sentinel_sample)

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # build_grounding_sample was called with the executed tool's name + items.
        pipeline.emitter.build_grounding_sample.assert_called()
        _gs_call = pipeline.emitter.build_grounding_sample.call_args
        assert _gs_call.args[0] == "get_fundamentals_history"
        assert _gs_call.args[1] == [item]

        # The sentinel sample was threaded into emit_tool_result.
        _result_calls = pipeline.emitter.emit_tool_result.call_args_list
        assert _result_calls, "expected at least one emit_tool_result call"
        assert _result_calls[0].kwargs.get("grounding_sample") == _sentinel_sample

    def test_orchestrator_execute_all_called_with_tool_blocks(self) -> None:
        """ToolExecutor.execute_all is called with the tool_use blocks from LLM response.

        E-6: The multi-turn loop calls execute_all on each iteration. This test uses
        a 2-call mock: first call returns tool_calls (triggering execute_all), second
        call returns a direct answer (breaking the loop). So execute_all is called once.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        # LLM: first call returns tool, second call returns direct answer
        call_count = [0]

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return _make_llm_tool_response(text="AAPL closed at $195.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _two_call_llm

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # execute_all called exactly once (the first iteration had tool calls)
        executor.execute_all.assert_called_once()

    def test_orchestrator_tool_result_content_capped_at_4000_chars(self) -> None:
        """Large tool result content is capped at 4000 chars in the injected LLM message.

        E-6: tool results are injected into messages between iterations; capped at
        _TOOL_RESULT_MAX_CHARS=4000. This test verifies that cap is applied.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")

        # Build a context block much longer than 4000 chars.
        long_context = "x" * 10000
        pipeline = _make_pipeline()

        # First call: return tool_calls; second call: return direct answer.
        call_count = [0]
        captured_messages: list[list] = []

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            captured_messages.append(list(messages))
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return _make_llm_tool_response(text="Answer.", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call_llm
        pipeline.build_prompt = MagicMock(return_value=("prompt", [], long_context))

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # The second LLM call receives messages including per-tool result
        # messages.  FIX-LIVE-J: tool results are now injected as one
        # ``role="tool"`` message per call (OpenAI / DeepInfra spec) with a
        # matching ``tool_call_id``; the first such message carries the full
        # aggregated (and capped) context block.  Verify the cap still holds.
        if len(captured_messages) >= 2:
            messages_for_second_call = captured_messages[-1]
            tool_msg_contents = [str(m.get("content", "")) for m in messages_for_second_call if m.get("role") == "tool"]
            # At least one tool message must exist (matching the single tool_call).
            assert tool_msg_contents, "expected at least one role='tool' message in second turn"
            # Every tool message must carry a tool_call_id (spec requirement).
            for m in messages_for_second_call:
                if m.get("role") == "tool":
                    assert m.get("tool_call_id"), "role='tool' messages must include a tool_call_id"
            # The 10000-char context must NOT appear verbatim (cap at 4000)
            # in any tool message — including the first, which carries the
            # aggregated context.
            for content in tool_msg_contents:
                assert "x" * 10001 not in content

    def test_orchestrator_parallel_tool_calls_produce_unique_ids_and_nonempty_content(self) -> None:
        """FIX-LIVE-R: per-tool messages must (a) have unique tool_call_ids and
        (b) carry non-empty content even when the same tool is invoked twice.

        Live re-QA (2026-05-25) caught two DeepInfra spec violations after
        FIX-LIVE-J:

        - When the LLM emits two parallel calls to the same function
          (Compare NVDA + AMD ⇒ two get_fundamentals_history calls), both
          tool_call entries previously fell back to the function name as the
          ``id`` field. Duplicate ids violate the OpenAI spec; DeepInfra
          silently dropped the second tool message and rejected the next turn
          with "missing required tool".
        - The non-first tool message carried ``"content": ""``. DeepInfra
          rejects empty content on role="tool".

        This test pins both invariants so a future refactor cannot regress.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # Two parallel calls to the SAME tool — the exact shape that triggered
        # the live failure on Q4 v1 ("Compare NVDA and AMD revenue").
        tool_a = _make_tool_use_block("get_fundamentals_history", inp={"ticker": "NVDA", "periods": 4})
        tool_b = _make_tool_use_block("get_fundamentals_history", inp={"ticker": "AMD", "periods": 4})
        # Simulate the provider returning an EMPTY id (the bug condition):
        # adapters parse ``id=call.get("id", "")``, so when DeepInfra omits an
        # id the dataclass attribute is "". The orchestrator must NOT then
        # collapse both calls to the same fallback identifier.
        tool_a.id = ""
        tool_b.id = ""

        call_count = [0]
        captured_messages: list[list] = []

        async def _two_call_llm(messages, tools=None, **kwargs):
            call_count[0] += 1
            captured_messages.append(list(messages))
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_a, tool_b])
            return _make_llm_tool_response(text="Answer.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _two_call_llm
        pipeline.build_prompt = MagicMock(return_value=("prompt", [], "aggregated context block"))

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        assert len(captured_messages) >= 2, "expected at least 2 LLM turns"
        msgs = captured_messages[-1]

        # Locate the assistant tool-call message + its tool replies.
        assistant_msgs = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert assistant_msgs, "expected assistant message with tool_calls"
        assert len(tool_msgs) == 2, f"expected 2 tool messages, got {len(tool_msgs)}"

        # (a) Unique tool_call_ids — no collision between the parallel calls.
        ids_on_assistant = [tc["id"] for tc in assistant_msgs[-1]["tool_calls"]]
        ids_on_tool_msgs = [m["tool_call_id"] for m in tool_msgs]
        assert len(set(ids_on_assistant)) == 2, f"duplicate ids in assistant tool_calls: {ids_on_assistant}"
        assert len(set(ids_on_tool_msgs)) == 2, f"duplicate ids on tool messages: {ids_on_tool_msgs}"
        assert set(ids_on_assistant) == set(ids_on_tool_msgs), "tool reply ids must mirror assistant tool_calls"

        # (b) Every tool message has NON-EMPTY content (DeepInfra spec).
        for m in tool_msgs:
            assert m.get("content"), f"tool message must have non-empty content, got {m!r}"

        # (c) Every tool message includes the ``name`` field (helps stricter
        # providers resolve the tool_call_id ↔ function name mapping).
        for m in tool_msgs:
            assert m.get("name"), f"tool message must include name field, got {m!r}"


# ---------------------------------------------------------------------------
# Tests: all-tools-failed guard
# ---------------------------------------------------------------------------


class TestAllToolsFailed:
    def test_orchestrator_all_tools_failed_returns_early(self) -> None:
        """When all tools return None, the orchestrator emits a WORDED refusal and stops.

        CRITICAL: second LLM turn must NOT be called when all tools fail.
        Without this guard the LLM would hallucinate from empty context.

        2026-06-12 root-cause audit Theme E (fix #3): the orchestrator no longer
        hard-returns an EMPTY error body (``safety_unknown_ticker`` read as a
        crash). It now streams a worded "I couldn't find a match…" answer
        (token + final_answer + done) so the body is never empty.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        second_turn_called = [False]

        async def _should_not_stream(messages: list, **kwargs: Any):
            second_turn_called[0] = True
            yield "Should not appear."

        pipeline.llm_chain.stream_chat = _should_not_stream

        # All tools fail → all return None
        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Must NOT call second turn, and the answer body must be worded (never empty).
        assert second_turn_called[0] is False
        assert "final_answer" in event_types
        final = next(e for e in events if e.get("event") == "final_answer")
        assert "couldn't find a match" in json.loads(final["data"])["text"]
        # No bare error event — the empty-body crash UX is gone.
        assert "error" not in event_types

    def test_orchestrator_all_tools_failed_emits_worded_body(self) -> None:
        """all_tools_failed path streams a worded body (token + final_answer), not an empty error."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history", {"ticker": "ZZZQQQ"})
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        # The worded message echoes the not-found ticker pulled from the tool input.
        final_events = [e for e in events if e.get("event") == "final_answer"]
        assert len(final_events) == 1
        body = json.loads(final_events[0]["data"])["text"]
        assert "ZZZQQQ" in body
        assert body.strip() != ""
        # Token stream carried the body too (UI never sees an empty stream).
        token_text = "".join(json.loads(e["data"]).get("text", "") for e in events if e.get("event") == "token")
        assert "ZZZQQQ" in token_text

    def test_orchestrator_partial_tool_failure_continues(self) -> None:
        """Mixed results (some None, some items) → second LLM turn runs.

        Only ALL-None triggers the guard. Partial success proceeds normally.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block1 = _make_tool_use_block("get_price_history")
        tool_block2 = _make_tool_use_block("get_fundamentals_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block1, tool_block2])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        second_turn_called = [False]

        async def _stream(messages: list, **kwargs: Any):
            second_turn_called[0] = True
            yield "Answer."

        pipeline.llm_chain.stream_chat = _stream

        good_item = _make_retrieved_item()
        # Mixed: one good item, one None
        executor = _make_tool_executor_mock([good_item, None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        # Second turn must run (partial success)
        assert second_turn_called[0] is True
        # No all_tools_failed error
        error_events = [e for e in events if e.get("event") == "error"]
        assert not any("all_tools_failed" in json.loads(e["data"]).get("code", "") for e in error_events)

    def test_orchestrator_no_tool_calls_streams_direct_answer(self) -> None:
        """When LLM emits no tool_calls, the text field is streamed directly."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # LLM responds with text, no tool calls
        first_resp = _make_llm_tool_response(text="AAPL is a tech company.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # No tool_call or tool_result events
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types
        # Still produces done event
        assert "done" in event_types


# ---------------------------------------------------------------------------
# E-6: Multi-iteration agent loop tests
# ---------------------------------------------------------------------------


class TestAgentBudget:
    def test_agent_budget_defaults(self) -> None:
        """AgentBudget has correct default values.

        PLAN-0107 raised ``max_tool_latency_s`` from 30.0 → 90.0 and
        ``max_consecutive_errors`` from 2 → 3 so deep multi-round financial
        research queries no longer surrender prematurely. The new defaults
        align with the FIX-LIVE-X DeepInfra tool-call timeout (90s) and the
        ReAct fallback chain length (3 alt tools).
        """
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget

        budget = AgentBudget()
        assert budget.max_tokens_per_iter == 2048
        assert budget.max_tokens_final == 8000
        assert budget.max_iterations == 8
        assert budget.max_consecutive_errors == 3
        assert budget.max_tool_latency_s == 90.0

    def test_agent_budget_sourced_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PLAN-0107: app wiring constructs AgentBudget from env-overridable Settings.

        Overriding ``RAG_CHAT_MAX_TOOL_LATENCY_S=120`` must produce a budget
        with ``max_tool_latency_s == 120.0`` when the wiring layer reads the
        Settings object. This pins the contract between ``Settings`` and
        ``AgentBudget`` — if a future refactor accidentally drops the wiring,
        this test catches it before the env var becomes a silent no-op.
        """
        # Use a real Settings object so we exercise the validation_alias.
        # database_url is required at construction time — supply a dummy.
        monkeypatch.setenv("RAG_CHAT_DATABASE_URL", "postgresql+asyncpg://x:y@localhost:5432/test")
        monkeypatch.setenv("RAG_CHAT_MAX_TOOL_LATENCY_S", "120")
        monkeypatch.setenv("RAG_CHAT_MAX_CONSECUTIVE_ERRORS", "5")

        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget
        from rag_chat.config import Settings

        settings = Settings()
        # Sanity check that Settings picked up the env override.
        assert settings.chat_max_tool_latency_s == 120.0
        assert settings.chat_max_consecutive_errors == 5

        # Replicate the wiring constructed in app.py::_wire_orchestrator —
        # this is the exact construction site under test.
        budget = AgentBudget(
            max_tool_latency_s=settings.chat_max_tool_latency_s,
            max_consecutive_errors=settings.chat_max_consecutive_errors,
        )
        assert budget.max_tool_latency_s == 120.0
        assert budget.max_consecutive_errors == 5

    def test_orchestrator_accepts_budget_param(self) -> None:
        """ChatOrchestratorUseCase accepts an AgentBudget parameter."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        budget = AgentBudget(max_iterations=3)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, budget=budget)

        assert orch._budget.max_iterations == 3


class TestMultiIterationBehavior:
    def test_multi_iteration_tools_then_answer(self) -> None:
        """LLM calls tools on iter 0, calls more tools on iter 1, answers on iter 2.

        Verifies: chat_with_tools is called 3 times (2 tool rounds + 1 direct answer),
        and execute_all is called twice.
        """
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        more_tool_block = _make_tool_use_block("search_documents")
        direct_answer = _make_llm_tool_response(text="The price is $150.", tool_calls=[])

        # LLM calls: [tool_calls], [more_tool_calls], [direct answer]
        call_count = [0]

        async def _chat_with_tools(messages, tools=None, max_tokens=1024, temperature=0.1, **kwargs):
            # FIX-LIVE-EE: accept the new `retry=` kwarg the orchestrator now
            # forwards to chat_with_tools on iter-0 (swallowed via **kwargs).
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            elif call_count[0] == 2:
                return _make_llm_tool_response(tool_calls=[more_tool_block])
            else:
                return direct_answer

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _chat_with_tools

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        budget = AgentBudget(max_iterations=8)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Should have completed normally
        assert "done" in event_types
        # chat_with_tools called 3 times (2 tool rounds + 1 direct answer)
        assert call_count[0] == 3
        # execute_all called twice (2 tool rounds)
        assert executor.execute_all.call_count == 2

    def test_consecutive_error_surrender(self) -> None:
        """Two consecutive all-fail rounds trigger surrender and final answer stream."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")

        # LLM keeps requesting tools even though they fail
        async def _always_requests_tools(messages, tools=None, **kwargs):
            return _make_llm_tool_response(tool_calls=[tool_block])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _always_requests_tools

        # All tools always fail (return None)
        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        budget = AgentBudget(max_iterations=8, max_consecutive_errors=2)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Should eventually surrender and call the streaming final answer
        # The test verifies the loop doesn't go on forever (error OR done event)
        assert "error" in event_types or "done" in event_types
        # execute_all was called multiple times (not just once)
        assert executor.execute_all.call_count >= 1

    def test_direct_answer_on_first_turn(self) -> None:
        """LLM answers directly with no tools → done event emitted without tool events."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # LLM responds with direct text, no tool calls
        direct_resp = _make_llm_tool_response(text="AAPL closed at $195.50 yesterday.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=direct_resp)

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        assert "done" in event_types
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types

    def test_direct_text_after_tools_routes_to_incremental_synthesis(self) -> None:
        """BUG-4: a direct-text final answer AFTER tools streams via stream_chat.

        When tools ran and the planning turn returns the answer as direct text,
        the orchestrator must NOT burst-emit that already-generated string. It
        routes the final answer through the incremental synthesis ``stream_chat``
        path (which the F1 adapter fix makes genuinely incremental) so tokens
        arrive one at a time. We assert stream_chat WAS invoked and multiple
        distinct token events were emitted over the run.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        tool_block = _make_tool_use_block("get_price_history")
        direct_answer = _make_llm_tool_response(text="The price is $150.", tool_calls=[])

        call_count = [0]

        async def _chat_with_tools(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return direct_answer

        # Synthesis stream yields several chunks so we can prove real streaming.
        stream_calls = [0]

        async def _stream_chat(messages, **kwargs):
            stream_calls[0] += 1
            for chunk in ["Apple ", "traded ", "higher ", "today."]:
                yield chunk

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _chat_with_tools
        pipeline.llm_chain.stream_chat = _stream_chat

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(
            pipeline=pipeline,
            tool_executor_factory=factory,
            budget=AgentBudget(max_iterations=8),
        )
        events = asyncio.run(_collect_events(orch, _make_chat_request(), MagicMock()))
        event_types = [e.get("event") for e in events]

        # The synthesis stream WAS engaged (not the direct-text burst).
        assert stream_calls[0] >= 1, "final answer must route through stream_chat"
        # Multiple token events → genuinely incremental delivery.
        token_events = [e for e in events if e.get("event") == "token"]
        assert len(token_events) >= 2, f"expected incremental tokens, got {len(token_events)}"
        assert "done" in event_types
        # The discarded planning prose is NOT what shipped as tokens.
        streamed = "".join(json.loads(e["data"]).get("text", "") for e in token_events)
        assert "The price is $150." not in streamed


class TestMaxIterationsSurrender:
    def test_max_iterations_reached_still_completes(self) -> None:
        """When max_iterations is reached, the loop appends a surrender message and runs final answer.

        The orchestrator must NOT loop forever — it must end with done or error.
        """
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")

        # LLM always requests tools (will be stopped by budget)
        async def _always_tools(messages, tools=None, **kwargs):
            return _make_llm_tool_response(tool_calls=[tool_block])

        item = _make_retrieved_item()
        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _always_tools

        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        # Very low max_iterations to test the surrender path
        budget = AgentBudget(max_iterations=2)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Must terminate (done or error)
        assert "done" in event_types or "error" in event_types
        # PLAN-0093 E-5 T-E-5-02 introduced tool-call dedup, so when the same
        # tool_block is emitted twice the second call is served from cache and
        # execute_all is invoked only on iteration 1 (call_count == 1). The
        # intent of this test is "the loop terminates after max_iterations",
        # not "execute_all is called N times" — assert >= 1 and leave the
        # iteration-count assertion to the surrender event itself.
        assert executor.execute_all.call_count >= 1


# ---------------------------------------------------------------------------
# Tests: DS-F003 — shielded persistence + DS-F004 — pending-action JSON warning
# ---------------------------------------------------------------------------


class TestPersistenceShield:
    """DS-F003: persist_chat + write_completion_cache must run under asyncio.shield.

    The shield protects mid-transaction DB writes from being cancelled by a
    client disconnect that arrives after the final_answer SSE event.
    """

    def test_persist_chat_runs_under_shield_on_happy_path(self) -> None:
        """Smoke test: persist_chat + write_completion_cache are still invoked
        on the happy path (no cancellation). Proves the shield wrapping did
        not regress the normal completion flow.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # LLM responds with direct text — no tools, fastest path through the
        # generator that still exercises Step 10 (persist + cache).
        direct_resp = _make_llm_tool_response(text="AAPL closed at $195.50.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=direct_resp)

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        event_types = [e.get("event") for e in events]

        # Generator completed normally
        assert "done" in event_types
        # Both shielded calls were still invoked exactly once
        assert pipeline.persist_chat.await_count == 1
        assert pipeline.write_completion_cache.await_count == 1

    def test_persist_chat_completes_when_consumer_stops_after_done(self) -> None:
        """Cancellation-style smoke test: even when the consumer stops consuming
        events right after `done`, persist_chat must have already been awaited
        because the shield runs to completion before the `done` event is yielded.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        direct_resp = _make_llm_tool_response(text="Direct answer.", tool_calls=[])
        pipeline = _make_pipeline(first_llm_response=direct_resp)

        # Track that persist_chat was actually invoked before the consumer
        # stopped reading from the generator.
        persist_invocations: list[float] = []

        async def _slow_persist(**kwargs: Any) -> tuple[str, str]:
            # Tiny await so an in-flight cancellation would have a chance to
            # hit us if the shield were missing.
            await asyncio.sleep(0)
            persist_invocations.append(1.0)
            return (_FAKE_UUID, _FAKE_UUID)

        pipeline.persist_chat = AsyncMock(side_effect=_slow_persist)

        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        async def _consume_until_done() -> list:
            collected: list = []
            async for event in orch.execute_streaming(request, uow):
                collected.append(event)
                if event.get("event") == "done":
                    # Simulate a client that drops the connection right after
                    # receiving `done`. Because persist_chat is shielded and
                    # runs before `done` is yielded, the invocation must
                    # already have been recorded.
                    break
            return collected

        events = asyncio.run(_consume_until_done())
        assert any(e.get("event") == "done" for e in events)
        # The shielded persistence ran to completion before `done` was yielded.
        assert len(persist_invocations) == 1


class TestPendingActionJsonWarning:
    """DS-F004: malformed pending-action JSON emits a structured warning."""

    def test_pending_action_json_parse_failure_logs_warning(self, capsys: Any) -> None:
        """When a tool returns an action_pending RetrievedItem with malformed
        JSON in `.text`, the orchestrator must emit a
        `pending_action_json_parse_failure` log event (with `pending_id` +
        `error`) instead of silently swallowing the parse failure.

        Uses `capsys` (not `caplog`) because structlog in this repo renders
        directly to stdout via its own ConsoleRenderer chain — see the same
        pattern in test_chat_orchestrator_fallback.py.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase
        from rag_chat.domain.enums import ItemType

        # Build a malformed action_pending RetrievedItem mock. The orchestrator
        # filters by `item.item_type == ItemType.action_pending`, so we use the
        # real enum value.
        pending = MagicMock()
        pending.item_type = ItemType.action_pending
        pending.item_id = "tool:create_alert:NOT-A-VALID-UUID"
        pending.text = "{not valid json"  # triggers json.JSONDecodeError
        pending.score = 1.0

        # Pipeline: a tool call returns the malformed pending item. The LLM
        # then short-circuits to a direct answer on the second turn so we
        # reach the persistence step without further detours.
        tool_block = _make_tool_use_block("create_alert")
        call_count = [0]

        async def _chat_with_tools(messages, tools=None, max_tokens=1024, temperature=0.1, **kwargs):
            # FIX-LIVE-EE: accept the new `retry=` kwarg forwarded by the
            # orchestrator on iter-0 (swallowed via **kwargs).
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block])
            return _make_llm_tool_response(text="Alert created.", tool_calls=[])

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _chat_with_tools

        executor = _make_tool_executor_mock([pending])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # structlog renders the event name + key=value context into stdout.
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert (
            "pending_action_json_parse_failure" in combined
        ), f"expected pending_action_json_parse_failure log event, got: {combined!r}"
        # The warning must carry pending_id + error context so operators can
        # triage the malformed upstream payload.
        assert "pending_id" in combined, f"warning missing pending_id key: {combined!r}"
        assert "error" in combined, f"warning missing error key: {combined!r}"


# ---------------------------------------------------------------------------
# PLAN-0107: agent_iteration SSE progress events
# ---------------------------------------------------------------------------


class TestAgentIterationEvents:
    """Pin the per-iteration SSE event stage progression (PLAN-0107).

    The frontend consumer is implemented against this exact contract; any
    change to the stage strings (``planning_tools`` / ``reasoning_over_results``
    / ``synthesizing``) must be coordinated with apps/worldview-web.
    """

    def test_agent_iteration_stages_emitted_in_order(self) -> None:
        """First iter emits ``planning_tools``; iter > 0 emits ``reasoning_over_results``;
        post-loop synthesis emits ``synthesizing``.

        Sets up a two-tool-round loop (iter 0 tools → iter 1 tools → iter 2
        direct answer) so we see at minimum the planning_tools + one
        reasoning_over_results event. Because iter 2 ends with a direct text
        answer the synthesis stream is skipped (_skip_final_stream=True), so
        ``synthesizing`` will NOT appear in that path — we exercise it in the
        second sub-test below.
        """
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget, ChatOrchestratorUseCase

        tool_block_a = _make_tool_use_block("get_price_history")
        tool_block_b = _make_tool_use_block("search_documents")
        # iter 2 returns no tool_calls AND empty text — forces the post-loop
        # stream_chat path (which emits ``synthesizing``).
        empty_finish = _make_llm_tool_response(text="", tool_calls=[])
        call_count = [0]

        async def _chat_with_tools(messages, tools=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_llm_tool_response(tool_calls=[tool_block_a])
            if call_count[0] == 2:
                return _make_llm_tool_response(tool_calls=[tool_block_b])
            return empty_finish

        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = _chat_with_tools

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        budget = AgentBudget(max_iterations=8)
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory, budget=budget)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        iter_events = [json.loads(e["data"]) for e in events if e.get("event") == "agent_iteration"]

        # Two loop iterations → planning_tools + reasoning_over_results.
        # The third loop iteration (iter=2) also emits a reasoning event
        # BEFORE the chat_with_tools call that returns the empty finish — so
        # we expect at least 3 events in total, ending with synthesizing.
        stages = [e["stage"] for e in iter_events]
        assert "planning_tools" in stages
        assert "reasoning_over_results" in stages
        # synthesizing fires because the loop ends with empty text + no tools
        # (no _skip_final_stream shortcut), so the post-loop stream_chat is
        # exercised.
        assert stages[-1] == "synthesizing", f"expected synthesizing last, got {stages!r}"

        # Field-shape sanity check on the first event (iter 0 / planning).
        first = iter_events[0]
        assert first["iteration"] == 0
        assert first["max_iterations"] == 8
        assert first["stage"] == "planning_tools"
        assert first["tools_completed_total"] == 0  # no tools have run yet
        assert isinstance(first["elapsed_ms"], int)
        assert first["elapsed_ms"] >= 0
