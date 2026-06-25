"""Tests for the synthesis-turn system-prompt swap (Fix #1).

When the orchestrator calls ``stream_chat`` for the post-tool synthesis
turn, the first message (system prompt) MUST be the minimal
SYNTHESIS_SYSTEM_PROMPT — not the planning-turn TOOL_USE prompt that
teaches the model how to call tools.

We also assert that ``tools=[]`` is forwarded so the adapter can set
``tool_choice="none"`` (Fix #2 wiring).
"""

from __future__ import annotations

import asyncio
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


def _make_tool_use_block() -> MagicMock:
    block = MagicMock()
    block.name = "get_fundamentals_history"
    block.input = {"entity_id": "aaaa-1111"}
    block.tool_use_id = "call_get_fundamentals_history"
    return block


def _make_retrieved_item() -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:fundamentals:AAPL"
    item.text = "Apple Q3 revenue was $10.253B per the filing."
    item.score = 0.9
    item.value = None
    item.field_kind = None
    return item


def _make_pipeline_and_capture() -> tuple[MagicMock, list[tuple[list[dict[str, Any]], dict[str, Any]]]]:
    """Pipeline whose stream_chat records (messages, kwargs) per call."""
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

    captured: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    async def _stream_chat(messages: list, **kwargs: Any):
        captured.append((list(messages), dict(kwargs)))
        # Emit a clean answer matching the tool data so grounding passes
        # and no rewrite is triggered (we only care about the FIRST call).
        for chunk in ["Apple Q3 revenue was $10.253B."]:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()
    return pipeline, captured


def _make_executor(return_items: list) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_fundamentals_history")
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_request() -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What was Apple's Q3 revenue?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


async def _collect(orch: Any, request: Any, uow: Any) -> None:
    async for _ev in orch.execute_streaming(request, uow):
        pass


class TestSynthesisPromptSwap:
    def _build(self):
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline, captured = _make_pipeline_and_capture()
        block = _make_tool_use_block()
        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = MagicMock()
        factory.for_request = MagicMock(return_value=executor)

        ct = {"i": 0}

        async def _two_call(messages, tools=None, **_):
            ct["i"] += 1
            if ct["i"] == 1:
                return _make_llm_tool_response(tool_calls=[block])
            return _make_llm_tool_response(text="", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        return orch, captured

    def test_synthesis_turn_uses_synthesis_system_prompt(self) -> None:
        """Message[0] for the synthesis stream_chat call is SYNTHESIS_SYSTEM_PROMPT."""
        orch, captured = self._build()
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        assert captured, "stream_chat was never called"
        synthesis_messages, _kwargs = captured[0]
        assert synthesis_messages[0]["role"] == "system"
        system_text = synthesis_messages[0]["content"]
        # SYNTHESIS_SYSTEM_PROMPT signature lines.
        assert "FINAL answer" in system_text
        assert "FORBIDDEN" in system_text
        # Must NOT contain planning-turn-only directives.
        assert "MACRO COMPOSITION" not in system_text
        assert "SCREENER" not in system_text
        assert "tool_choice" not in system_text.lower()

    def test_synthesis_turn_forwards_empty_tools(self) -> None:
        """The synthesis stream_chat call passes tools=[] (Fix #2 wiring)."""
        orch, captured = self._build()
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        _msgs, kwargs = captured[0]
        assert (
            kwargs.get("tools") == []
        ), f"synthesis turn must call stream_chat with tools=[], got tools={kwargs.get('tools')!r}"

    def test_synthesis_turn_preserves_assistant_and_tool_messages(self) -> None:
        """Only message[0] is swapped; the assistant + tool history is intact."""
        orch, captured = self._build()
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        synthesis_messages, _ = captured[0]
        # Must include the user question + the tool round-trip messages.
        roles = [m["role"] for m in synthesis_messages]
        assert "user" in roles
        # At least the system + user; tool/assistant blocks added during the loop
        # should appear too — assert length >= 3 (system + user + at least one
        # tool-loop message).
        assert len(synthesis_messages) >= 3
