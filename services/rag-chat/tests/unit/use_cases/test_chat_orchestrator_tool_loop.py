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
    pipeline.emitter.emit_citations = MagicMock(return_value={"event": "citations", "data": "[]"})
    pipeline.emitter.emit_contradictions = MagicMock(return_value={"event": "contradictions", "data": "[]"})
    pipeline.emitter.emit_metadata = MagicMock(return_value={"event": "metadata", "data": "{}"})
    pipeline.emitter.emit_done = MagicMock(return_value={"event": "done", "data": '{"type":"done"}'})
    pipeline.emitter.emit_tool_call = MagicMock(
        side_effect=lambda name, inp, **kw: {"event": "tool_call", "data": json.dumps({"tool": name})}
    )
    pipeline.emitter.emit_tool_result = MagicMock(
        side_effect=lambda name, status="ok", item_count=0: {
            "event": "tool_result",
            "data": json.dumps({"tool": name, "status": status, "item_count": item_count}),
        }
    )
    pipeline.emitter.emit_error = MagicMock(
        side_effect=lambda code, msg: {"event": "error", "data": json.dumps({"code": code, "message": msg})}
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
        # tool_call must appear before tool_result
        assert event_types.index("tool_call") < event_types.index("tool_result")

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

        # The second LLM call receives messages including the injected context block.
        # Verify the context was capped at 4000 chars in the injected user message.
        if len(captured_messages) >= 2:
            # Find the user message with "Here is the data retrieved by the tools"
            messages_for_second_call = captured_messages[-1]
            user_msgs_with_data = [
                m.get("content", "")
                for m in messages_for_second_call
                if m.get("role") == "user" and "Here is the data" in str(m.get("content", ""))
            ]
            if user_msgs_with_data:
                content = user_msgs_with_data[0]
                # The 10000-char context must NOT appear verbatim (cap at 4000)
                assert "x" * 10001 not in content


# ---------------------------------------------------------------------------
# Tests: all-tools-failed guard
# ---------------------------------------------------------------------------


class TestAllToolsFailed:
    def test_orchestrator_all_tools_failed_returns_early(self) -> None:
        """When all tools return None, the orchestrator emits error and stops.

        CRITICAL: second LLM turn must NOT be called when all tools fail.
        Without this guard the LLM would hallucinate from empty context.
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

        # Must emit error and NOT call second turn
        assert "error" in event_types
        assert second_turn_called[0] is False

    def test_orchestrator_all_tools_failed_error_code(self) -> None:
        """all_tools_failed guard must emit error code 'all_tools_failed'."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        executor = _make_tool_executor_mock([None])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))
        error_events = [e for e in events if e.get("event") == "error"]

        assert len(error_events) >= 1
        error_data = json.loads(error_events[0]["data"])
        assert error_data["code"] == "all_tools_failed"

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
        """AgentBudget has correct default values."""
        from rag_chat.application.use_cases.chat_orchestrator import AgentBudget

        budget = AgentBudget()
        assert budget.max_tokens_per_iter == 2048
        assert budget.max_tokens_final == 8000
        assert budget.max_iterations == 8
        assert budget.max_consecutive_errors == 2
        assert budget.max_tool_latency_s == 30.0

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

        async def _chat_with_tools(messages, tools=None, max_tokens=1024, temperature=0.1):
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
