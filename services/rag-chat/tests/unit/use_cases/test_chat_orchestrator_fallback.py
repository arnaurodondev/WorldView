"""Tests for PLAN-0093 Wave E-4 T-E-4-03 — multi-tool fallback in the orchestrator.

When a tool returns 0 items on iteration 0, the orchestrator tries ONE
alternate tool from a fallback map (search_documents → get_entity_intelligence,
get_contradictions → search_claims polarity=negative, etc.) before
surfacing PROVIDER_UNAVAILABLE.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000002"


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str, inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"query": "MSTR news"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_retrieved_item(item_id: str = "tool:fallback:1") -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = item_id
    item.text = "Fallback tool data."
    item.score = 0.7
    item.value = None
    item.field_kind = None
    return item


def _make_pipeline() -> MagicMock:
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("system prompt", [], "context"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(side_effect=lambda text, items: (text, []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    async def _stream_chat(messages: list, **kwargs: Any):
        yield "Streamed answer using fallback data."

    pipeline.llm_chain.stream_chat = _stream_chat

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()
    return pipeline


def _make_executor_with_callable(execute_all_callable: Any) -> MagicMock:
    """Build a mock executor whose execute_all is async-callable per test."""
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- search_documents")
    executor._registry = registry
    executor.execute_all = execute_all_callable
    return executor


def _make_factory(executor: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


def _make_request() -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What is MSTR news?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


async def _collect(orch: Any, request: Any, uow: Any) -> list:
    events: list = []
    async for ev in orch.execute_streaming(request, uow):
        events.append(ev)
    return events


class TestMultiToolFallback:
    def test_search_documents_empty_falls_back_to_intelligence(self) -> None:
        """search_documents returns [] → orchestrator tries get_entity_intelligence."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("search_documents")
        pipeline = _make_pipeline()

        # chat_with_tools: iter 0 returns the failing tool, iter 1 returns
        # no calls (so the loop exits and we hit the streaming final turn).
        ct = {"i": 0}

        async def _two_call(messages, tools=None, **_):
            ct["i"] += 1
            if ct["i"] == 1:
                return _make_llm_tool_response(tool_calls=[block])
            return _make_llm_tool_response(text="", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call

        # execute_all returns [None] for the original call (empty) and
        # a real item for the fallback call.
        exec_calls = {"n": 0}

        async def _execute_all(tool_calls):
            exec_calls["n"] += 1
            if exec_calls["n"] == 1:
                # original search_documents → all empty
                return [None]
            # fallback call — return one item
            return [[_make_retrieved_item()]]

        executor = _make_executor_with_callable(_execute_all)
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        events = asyncio.run(_collect(orch, _make_request(), MagicMock()))

        # Must NOT emit the all_tools_failed error — fallback succeeded.
        event_types = [e.get("event") for e in events]
        assert "error" not in event_types
        assert "done" in event_types
        # execute_all was called twice: original + fallback.
        assert exec_calls["n"] == 2

    def test_double_empty_returns_503(self) -> None:
        """Both original AND fallback return empty → error event surfaces."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("search_documents")
        pipeline = _make_pipeline()
        pipeline.llm_chain.chat_with_tools = AsyncMock(return_value=_make_llm_tool_response(tool_calls=[block]))

        async def _execute_all(tool_calls):
            # Both original + fallback return empty.
            return [None]

        executor = _make_executor_with_callable(_execute_all)
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        events = asyncio.run(_collect(orch, _make_request(), MagicMock()))

        # all_tools_failed error event MUST be emitted.
        error_events = [e for e in events if e.get("event") == "error"]
        assert len(error_events) >= 1
        payload = json.loads(error_events[0]["data"])
        assert payload.get("code") == "all_tools_failed"

    def test_fallback_logged(self, capsys: Any) -> None:
        """Fallback attempt emits a structured log event."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        block = _make_tool_use_block("search_documents")
        pipeline = _make_pipeline()

        ct = {"i": 0}

        async def _two_call(messages, tools=None, **_):
            ct["i"] += 1
            if ct["i"] == 1:
                return _make_llm_tool_response(tool_calls=[block])
            return _make_llm_tool_response(text="", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call

        exec_calls = {"n": 0}

        async def _execute_all(tool_calls):
            exec_calls["n"] += 1
            if exec_calls["n"] == 1:
                return [None]
            return [[_make_retrieved_item()]]

        executor = _make_executor_with_callable(_execute_all)
        factory = _make_factory(executor)

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "tool_fallback_attempted" in combined
        assert "tool_fallback_succeeded" in combined
