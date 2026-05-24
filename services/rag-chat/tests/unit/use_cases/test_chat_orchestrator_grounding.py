"""Integration tests for the orchestrator's E-2 grounding hook.

PLAN-0093 Wave E-2, Task T-E-2-02.

Coverage:
- ``test_validator_invoked_after_tool_loop`` — the validator runs once
  per turn after the LLM produces its final answer.
- ``test_failed_grounding_triggers_one_rewrite`` — invented number →
  2 LLM stream_chat calls (initial + rewrite).
- ``test_second_failure_appends_banner`` — both passes fail → response
  ends with the warning banner.
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


def _make_tool_use_block(name: str = "get_fundamentals_history", inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"entity_id": "aaaa-1111"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_retrieved_item(text: str = "Apple Q3 revenue was $10.253B per the filing.") -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:fundamentals:AAPL"
    item.text = text
    item.score = 0.9
    # No structured value/field_kind on this stub — the validator falls
    # back to scanning .text for numbers, which is the real-world path.
    item.value = None
    item.field_kind = None
    return item


def _make_pipeline(
    *,
    stream_chunks: list[str] | None = None,
    rewrite_chunks: list[str] | None = None,
) -> tuple[MagicMock, list[list[dict[str, Any]]]]:
    """Build a mock ChatPipeline and capture stream_chat invocations.

    Returns (pipeline, captured_messages_list). Each entry in
    captured_messages_list is the messages array passed to one
    stream_chat call, so the test can assert how many times the LLM was
    invoked AND inspect the rewrite prompt.
    """
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

    captured_messages: list[list[dict[str, Any]]] = []

    initial = stream_chunks or ["Q2 revenue was $34.6B per the filing."]
    rewrite = rewrite_chunks or ["Q2 revenue was $10.253B [N1]."]
    call_n = {"i": 0}

    async def _stream_chat(messages: list, **kwargs: Any):
        captured_messages.append(list(messages))
        call_n["i"] += 1
        # First call → initial draft. Second+ → rewrite.
        chunks = initial if call_n["i"] == 1 else rewrite
        for chunk in chunks:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()
    return pipeline, captured_messages


def _make_executor(return_items: list) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_fundamentals_history")
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
        message="What was Apple's Q2 revenue?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


async def _collect(orch: Any, request: Any, uow: Any) -> tuple[list, str]:
    """Run the streaming orchestrator and assemble the final answer text."""
    events: list = []
    async for ev in orch.execute_streaming(request, uow):
        events.append(ev)
    # Reconstruct the final answer from token events (sync API does this).
    answer = ""
    for ev in events:
        if ev.get("event") == "token":
            answer += json.loads(ev["data"]).get("text", "")
    return events, answer


class TestOrchestratorGroundingHook:
    def _build(self, **kwargs: Any) -> tuple[Any, list, MagicMock]:
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline, captured = _make_pipeline(**kwargs)
        # Tool round-trip: iteration 0 calls tool, iteration 1 returns no calls so
        # we exit the loop and the streaming final turn runs.
        block = _make_tool_use_block()
        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = _make_factory(executor)

        # chat_with_tools: first call returns tool_calls, second returns no calls.
        ct = {"i": 0}

        async def _two_call(messages, tools=None, **_):
            ct["i"] += 1
            if ct["i"] == 1:
                return _make_llm_tool_response(tool_calls=[block])
            return _make_llm_tool_response(text="", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        return orch, captured, pipeline

    def test_validator_invoked_after_tool_loop(self) -> None:
        """Healthy response (numbers in tool data) → validator passes, no rewrite."""
        # Tool item already contains "$10.253B" — and the streamed answer
        # echoes that exact number.
        orch, captured, _ = self._build(stream_chunks=["Apple Q3 revenue was $10.253B."])
        _, answer = asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # Validator passed → exactly one stream_chat call (no rewrite).
        assert len(captured) == 1
        assert "$10.253B" in answer

    def test_failed_grounding_triggers_one_rewrite(self) -> None:
        """Invented '$34.6B' → 2 stream_chat calls; persisted answer is the rewrite.

        Streaming mode emits the initial draft as tokens before validation
        runs (so the user sees something quickly). After validation, the
        validated text is what gets ``process_output``/``persist_chat`` —
        the audit log + DB row reflect the rewrite, not the bad draft.
        We assert via the ``persist_chat`` mock call args.
        """
        orch, captured, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            rewrite_chunks=["Q2 revenue was $10.253B [N1]."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # 2 LLM stream_chat calls: initial draft + rewrite.
        assert len(captured) == 2

        # Verify the rewritten answer was the one passed to persist_chat.
        assert pipeline.persist_chat.await_count == 1
        kwargs = pipeline.persist_chat.await_args.kwargs
        assistant_response = kwargs["assistant_response"]
        assert "$10.253B" in assistant_response.content
        assert "$34.6B" not in assistant_response.content

    def test_second_failure_appends_banner(self) -> None:
        """Both initial draft AND rewrite invent numbers → banner appended."""
        orch, captured, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            rewrite_chunks=["Actually Q2 revenue was $99.9B by my count."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # 2 calls — initial + one rewrite (the orchestrator does NOT loop
        # rewrites; one attempt then banner).
        assert len(captured) == 2
        # The persisted answer ends with the banner.
        assistant_response = pipeline.persist_chat.await_args.kwargs["assistant_response"]
        assert "could not be verified" in assistant_response.content
