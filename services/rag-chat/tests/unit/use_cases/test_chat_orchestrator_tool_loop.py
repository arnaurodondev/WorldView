"""Unit tests for ChatOrchestratorUseCase tool-use loop (PLAN-0066 Wave H T-W10-H-03).

Tests:
- test_orchestrator_no_tool_use_follows_existing_path
- test_orchestrator_tool_use_injects_results
- test_orchestrator_all_tools_failed_falls_back_to_classical
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
# Helpers: pipeline factory
# ---------------------------------------------------------------------------


def _async_token_gen(chunks: list[str]):
    """Return an async generator factory that yields (filtered, raw) tuples."""

    async def _gen(prompt: str, **kwargs: Any):
        for chunk in chunks:
            yield chunk, chunk

    return _gen


def _make_pipeline(llm_response: str = "Classical answer.") -> MagicMock:
    """Build a mock ChatPipeline for orchestrator tests."""
    from rag_chat.domain.enums import QueryIntent

    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.classify_and_plan = AsyncMock(return_value=(QueryIntent.FINANCIAL_DATA, [], "test query", _make_plan()))
    pipeline.expand_query = AsyncMock(return_value=(None, None))
    pipeline.embed_query = AsyncMock(return_value=[0.1] * 8)
    pipeline.retrieve = AsyncMock(return_value=[])
    pipeline.enrich_and_fuse = MagicMock(return_value=[])
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("test prompt", [], ""))
    pipeline.process_output = MagicMock(return_value=("Classical answer.", []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    # LLM stream: yields (filtered, raw) tuples
    async def _fake_stream(prompt: str, **kwargs: Any):
        for chunk in [llm_response]:
            yield chunk, chunk

    pipeline.stream_llm = _fake_stream
    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    # SSE emitter
    pipeline.emitter = MagicMock()
    pipeline.emitter.emit_status = MagicMock(return_value={"event": "status", "data": "{}"})
    pipeline.emitter.emit_token = MagicMock(side_effect=lambda t: {"event": "token", "data": json.dumps({"text": t})})
    pipeline.emitter.emit_citations = MagicMock(return_value={"event": "citations", "data": "[]"})
    pipeline.emitter.emit_contradictions = MagicMock(return_value={"event": "contradictions", "data": "[]"})
    pipeline.emitter.emit_metadata = MagicMock(return_value={"event": "metadata", "data": "{}"})
    pipeline.emitter.emit_done = MagicMock(return_value={"event": "done", "data": '{"type":"done"}'})
    pipeline.emitter.emit_tool_call = MagicMock(
        side_effect=lambda name, inp: {"event": "tool_call", "data": json.dumps({"tool": name})}
    )
    pipeline.emitter.emit_tool_result = MagicMock(
        side_effect=lambda name, ok: {
            "event": "tool_result",
            "data": json.dumps({"tool": name, "status": "ok" if ok else "error"}),
        }
    )

    return pipeline


def _make_plan():
    from rag_chat.domain.entities.chat import RetrievalPlan

    return RetrievalPlan(
        use_chunks=False,
        use_relations=False,
        use_graph=False,
        use_claims=False,
        use_events=False,
        use_contradictions=False,
        use_financial=True,
        use_portfolio=False,
        use_cypher=False,
        entity_ids=(),
    )


def _make_chat_request():
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What was AAPL's price last quarter?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


def _make_tool_executor_mock(return_items: list) -> MagicMock:
    """Build a mock ToolExecutor."""
    executor = MagicMock()
    executor._registry = MagicMock()
    executor._registry.to_system_prompt_section = MagicMock(return_value="```yaml\n- name: get_price_history\n```")
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_retrieved_item(text: str = "AAPL price history...") -> MagicMock:
    """Create a mock RetrievedItem."""
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:price_history:AAPL"
    item.text = text
    return item


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoToolUse:
    def test_orchestrator_no_tool_use_follows_existing_path(self) -> None:
        """When tool_executor=None (default), the classical pipeline runs unchanged.

        execute_all must never be called. The stream follows the normal token path.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline("Classical answer.")
        # No tool_executor — should behave exactly like pre-Wave-H
        orch = ChatOrchestratorUseCase(pipeline=pipeline)
        request = _make_chat_request()
        uow = MagicMock()

        events: list = []

        async def _run() -> None:
            async for event in orch.execute_streaming(request, uow):
                events.append(event)

        asyncio.run(_run())

        # Classical path: must never emit tool_call or tool_result events
        event_types = [e.get("event") for e in events]
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types
        # Must still complete with metadata and done events
        assert "metadata" in event_types
        assert "done" in event_types


class TestToolUseInjectsResults:
    def test_orchestrator_tool_use_injects_results(self) -> None:
        """When LLM emits a tool_use block, executor.execute_all is called and
        results are injected into a second LLM turn."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # First LLM turn returns a tool_use block; second turn returns a real answer
        first_response = (
            '{"type": "tool_use", "name": "get_price_history",'
            ' "input": {"ticker": "AAPL", "from_date": "2026-02-01", "to_date": "2026-05-01"}}'
        )
        second_response = "Based on the price data, AAPL rose 15% last quarter."

        pipeline = _make_pipeline(llm_response=first_response)
        # Make stream_llm return different values on successive calls
        call_count = [0]
        responses = [first_response, second_response]

        async def _alternating_stream(prompt: str, **kwargs: Any):
            idx = call_count[0]
            call_count[0] += 1
            chunk = responses[min(idx, len(responses) - 1)]
            yield chunk, chunk

        pipeline.stream_llm = _alternating_stream

        # ToolExecutor mock returns one successful item
        tool_item = _make_retrieved_item()
        executor = _make_tool_executor_mock(return_items=[tool_item])

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor=executor)
        request = _make_chat_request()
        uow = MagicMock()

        events: list = []

        async def _run() -> None:
            async for event in orch.execute_streaming(request, uow):
                events.append(event)

        asyncio.run(_run())

        # Tool executor must have been called
        executor.execute_all.assert_called_once()
        # SSE events must include tool_call and tool_result
        event_types = [e.get("event") for e in events]
        assert "tool_call" in event_types
        assert "tool_result" in event_types


class TestAllToolsFailed:
    def test_orchestrator_all_tools_failed_falls_back_to_classical(self) -> None:
        """When all tools return None, the orchestrator must log a warning and
        fall back to the classical path without calling a second LLM turn."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        first_response = (
            '{"type": "tool_use", "name": "get_price_history",'
            ' "input": {"ticker": "AAPL", "from_date": "2026-02-01", "to_date": "2026-05-01"}}'
        )
        pipeline = _make_pipeline(llm_response=first_response)

        call_count = [0]

        async def _one_shot_stream(prompt: str, **kwargs: Any):
            call_count[0] += 1
            yield first_response, first_response

        pipeline.stream_llm = _one_shot_stream

        # All tools fail → all return None
        executor = _make_tool_executor_mock(return_items=[None])

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor=executor)
        request = _make_chat_request()
        uow = MagicMock()

        events: list = []

        async def _run() -> None:
            async for event in orch.execute_streaming(request, uow):
                events.append(event)

        asyncio.run(_run())

        # Executor was called once
        executor.execute_all.assert_called_once()
        # Only 1 LLM turn: all-tools-failed guard must prevent second turn
        assert call_count[0] == 1
        # Stream still completes normally (metadata + done emitted)
        event_types = [e.get("event") for e in events]
        assert "done" in event_types

    def test_orchestrator_none_tool_results_filtered(self) -> None:
        """None items from execute_all are not added to the retrieved context.

        Mixed results: one good item, one None. Only the good item should be
        injected into the second LLM call's context.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        first_response = (
            '{"type": "tool_use", "name": "get_price_history",'
            ' "input": {"ticker": "AAPL", "from_date": "2026-02-01", "to_date": "2026-05-01"}}'
        )
        second_response = "Based on the data, AAPL performed well."
        pipeline = _make_pipeline(llm_response=first_response)

        call_count = [0]
        prompts_seen: list[str] = []

        async def _stream(prompt: str, **kwargs: Any):
            call_count[0] += 1
            prompts_seen.append(prompt)
            resp = first_response if call_count[0] == 1 else second_response
            yield resp, resp

        pipeline.stream_llm = _stream

        # Mixed: good item + None
        good_item = _make_retrieved_item()
        executor = _make_tool_executor_mock(return_items=[good_item, None])

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor=executor)
        request = _make_chat_request()
        uow = MagicMock()

        async def _run() -> None:
            async for _ in orch.execute_streaming(request, uow):
                pass

        asyncio.run(_run())

        # Two LLM turns (one tool call + one final answer)
        assert call_count[0] == 2
        # build_prompt was called twice (first turn + second turn with tool results)
        assert pipeline.build_prompt.call_count == 2


class TestOrchestratorDefaultConstructor:
    def test_orchestrator_default_no_tool_executor(self) -> None:
        """ChatOrchestratorUseCase(pipeline=...) still works without tool_executor arg."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline = _make_pipeline()
        orch = ChatOrchestratorUseCase(pipeline=pipeline)

        assert orch._tool_executor is None
