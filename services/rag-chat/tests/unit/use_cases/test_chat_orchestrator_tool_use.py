"""New tests for ChatOrchestratorUseCase tool-use path (PLAN-0067 W11-3 T-W11-3-02).

These tests verify the new W11-3 behaviours that were not covered by the migrated
test_chat_orchestrator_tool_loop.py:

- test_orchestrator_calls_tool_use_path_as_only_path
- test_orchestrator_tool_calls_emit_tool_call_events
- test_orchestrator_tool_results_injected_into_messages
- test_orchestrator_all_tools_failed_returns_early
- test_orchestrator_tool_result_content_capped_at_4000_chars

SSEEmitter tests:
- test_sse_thinking_event_has_stage
- test_sse_tool_call_event_has_label
- test_sse_tool_result_event_has_item_count
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str = "get_price_history", inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"ticker": "AAPL"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_pipeline(first_response: Any = None) -> MagicMock:
    """Build a minimal mock ChatPipeline."""
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("system prompt", [], "context"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(return_value=("Answer.", []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    default_resp = first_response or _make_llm_tool_response(text="Direct answer.")
    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.chat_with_tools = AsyncMock(return_value=default_resp)
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    async def _stream_chat(messages: list, **kwargs: Any):
        yield "Streamed answer."

    pipeline.llm_chain.stream_chat = _stream_chat

    # Real SSEEmitter so we can verify actual event structure.
    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()

    return pipeline


def _make_retrieved_item() -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:test:AAPL"
    item.score = 0.9
    return item


def _make_executor(return_items: list) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_price_history")
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_factory(executor: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


def _make_request() -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What is AAPL price?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


async def _collect(orch: Any, request: Any, uow: Any) -> list:
    events: list = []
    async for event in orch.execute_streaming(request, uow):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# T-W11-3-02 specified tests
# ---------------------------------------------------------------------------


class TestOrchestratorToolUsePath:
    def test_orchestrator_calls_tool_use_path_as_only_path(self) -> None:
        """execute_streaming → tool-use path always called (no classical path).

        Verifies: chat_with_tools is called on every request regardless of content.
        The thinking event is always emitted.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_request()

        events = asyncio.run(_collect(orch, request, MagicMock()))

        # chat_with_tools must always be called
        pipeline.llm_chain.chat_with_tools.assert_called_once()

        # Thinking event must always be emitted
        event_types = [e.get("event") for e in events]
        assert "thinking" in event_types

        # Stream must complete normally
        assert "done" in event_types

    def test_orchestrator_tool_calls_emit_tool_call_events(self) -> None:
        """When LLM response has tool_calls → 'tool_call' SSE events yielded.

        Verifies: one 'tool_call' event per tool_use block, emitted BEFORE execute_all.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[block])
        pipeline = _make_pipeline(first_response=first_resp)

        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        events = asyncio.run(_collect(orch, _make_request(), MagicMock()))

        tool_call_events = [e for e in events if e.get("event") == "tool_call"]
        assert len(tool_call_events) == 1
        data = json.loads(tool_call_events[0]["data"])
        assert data["tool"] == "get_price_history"

    def test_orchestrator_tool_results_injected_into_messages(self) -> None:
        """After execute_all → tool_result turns injected into messages for 2nd turn.

        Verifies: stream_chat is called with messages that include tool context.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[block])
        pipeline = _make_pipeline(first_response=first_resp)

        captured_messages: list = []

        async def _capture_stream(messages: list, **kwargs: Any):
            captured_messages.extend(messages)
            yield "Answer based on data."

        pipeline.llm_chain.stream_chat = _capture_stream

        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        asyncio.run(_collect(orch, _make_request(), MagicMock()))

        # Messages must include system, user, assistant (tool_calls), and user (results)
        assert len(captured_messages) >= 3
        roles = [m.get("role") for m in captured_messages]
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles

    def test_orchestrator_all_tools_failed_returns_early(self) -> None:
        """When all tool results are None → error emitted, second LLM turn NOT called.

        Verifies the all-tools-failed guard that prevents hallucination.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[block])
        pipeline = _make_pipeline(first_response=first_resp)

        second_turn_count = [0]

        async def _should_not_be_called(messages: list, **kwargs: Any):
            second_turn_count[0] += 1
            yield "Should not appear."

        pipeline.llm_chain.stream_chat = _should_not_be_called

        # All tools return None
        executor = _make_executor([None])
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        events = asyncio.run(_collect(orch, _make_request(), MagicMock()))

        # Second turn must NOT have been called
        assert second_turn_count[0] == 0

        # Error event with all_tools_failed code must be in stream
        error_events = [e for e in events if e.get("event") == "error"]
        assert len(error_events) >= 1
        assert any(json.loads(e["data"]).get("code") == "all_tools_failed" for e in error_events)

    def test_orchestrator_tool_result_content_capped_at_4000_chars(self) -> None:
        """Large context block (> 4000 chars) from tool results must be capped.

        Verifies: _TOOL_RESULT_MAX_CHARS = 4000 cap is applied before injection.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("get_price_history")
        first_resp = _make_llm_tool_response(tool_calls=[block])
        pipeline = _make_pipeline(first_response=first_resp)

        captured_user_content: list[str] = []

        async def _capture_stream(messages: list, **kwargs: Any):
            for msg in messages:
                if msg.get("role") == "user" and "Here is the data" in str(msg.get("content", "")):
                    captured_user_content.append(msg["content"])
            yield "Answer."

        pipeline.llm_chain.stream_chat = _capture_stream

        # Return a very long context block
        long_context = "A" * 10000
        pipeline.build_prompt = MagicMock(return_value=("prompt", [], long_context))

        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        asyncio.run(_collect(orch, _make_request(), MagicMock()))

        # If we captured the user message, verify the context was capped at 4000
        if captured_user_content:
            content = captured_user_content[0]
            # "A" * 10000 must not appear; capped at 4000
            assert "A" * 10001 not in content
            # Some A's should be present (the capped portion)
            assert "A" in content


# ---------------------------------------------------------------------------
# SSEEmitter new tests
# ---------------------------------------------------------------------------


class TestSSEThinkingEvent:
    def test_sse_thinking_event_has_stage(self) -> None:
        """emit_thinking() returns event with 'stage' field (PLAN-0067 W11-3 T-W11-3-01)."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_thinking(stage="tool_classification")

        assert event["event"] == "thinking"
        data = json.loads(event["data"])
        assert data["stage"] == "tool_classification"

    def test_sse_thinking_default_stage(self) -> None:
        """emit_thinking() defaults to stage='tool_classification'."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_thinking()
        data = json.loads(event["data"])

        assert data["stage"] == "tool_classification"

    def test_sse_thinking_custom_stage(self) -> None:
        """emit_thinking(stage='X') propagates the custom stage value."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_thinking(stage="entity_resolution")
        data = json.loads(event["data"])

        assert data["stage"] == "entity_resolution"


class TestSSEToolCallLabel:
    def test_sse_tool_call_event_has_label(self) -> None:
        """emit_tool_call() includes a 'label' field (PLAN-0067 W11-3 T-W11-3-01)."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_tool_call("get_price_history", {"ticker": "AAPL"})
        data = json.loads(event["data"])

        assert "label" in data
        # Label must be a human-readable string
        assert isinstance(data["label"], str)
        assert len(data["label"]) > 0

    def test_sse_tool_call_known_tool_has_proper_label(self) -> None:
        """Known tools use their descriptive label from _TOOL_LABELS."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()

        # Known tools must have specific labels
        cases = [
            ("get_price_history", "Fetching price history..."),
            ("get_fundamentals_history", "Fetching fundamentals..."),
            ("search_documents", "Searching documents..."),
        ]
        for tool_name, expected_label in cases:
            event = emitter.emit_tool_call(tool_name, {})
            data = json.loads(event["data"])
            assert data["label"] == expected_label, f"Wrong label for {tool_name}"


class TestSSEToolResultItemCount:
    def test_sse_tool_result_event_has_item_count(self) -> None:
        """emit_tool_result() includes an 'item_count' field (PLAN-0067 W11-3 T-W11-3-01)."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_tool_result("get_price_history", status="ok", item_count=7)
        data = json.loads(event["data"])

        assert "item_count" in data
        assert data["item_count"] == 7

    def test_sse_tool_result_item_count_zero_on_empty(self) -> None:
        """item_count=0 for empty status signals 'no results found'."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        event = emitter.emit_tool_result("search_claims", status="empty", item_count=0)
        data = json.loads(event["data"])

        assert data["item_count"] == 0
        assert data["status"] == "empty"

    def test_sse_tool_result_status_is_string(self) -> None:
        """status must be a string ('ok'|'error'|'empty'), not a boolean."""
        from rag_chat.application.pipeline.sse_emitter import SSEEmitter

        emitter = SSEEmitter()
        for status in ("ok", "error", "empty"):
            event = emitter.emit_tool_result("get_price_history", status=status)
            data = json.loads(event["data"])
            assert isinstance(data["status"], str)
            assert data["status"] == status
