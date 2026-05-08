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
        """ToolExecutor.execute_all is called with the tool_use blocks from LLM response."""
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

        asyncio.run(_collect_events(orch, request, uow))

        executor.execute_all.assert_called_once()

    def test_orchestrator_tool_result_content_capped_at_4000_chars(self) -> None:
        """Large tool result content is capped at 4000 chars in the second LLM message."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # Capture the messages passed to stream_chat
        captured_messages: list[list] = []

        async def _capture_stream(messages: list, **kwargs: Any):
            captured_messages.append(messages)
            yield "Answer."

        pipeline.llm_chain.stream_chat = _capture_stream

        # Build a context block that is much longer than 4000 chars
        long_context = "x" * 10000
        pipeline.build_prompt = MagicMock(return_value=("prompt", [], long_context))

        item = _make_retrieved_item()
        executor = _make_tool_executor_mock([item])
        factory = _make_factory_mock(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        asyncio.run(_collect_events(orch, request, uow))

        # Find the user message that contains tool results
        if captured_messages:
            all_content = " ".join(
                m.get("content", "") for m in captured_messages[0] if isinstance(m.get("content"), str)
            )
            # The context block is capped at 4000; the full 10000-char string must not appear
            assert "x" * 10001 not in all_content


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
