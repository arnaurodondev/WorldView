"""Unit tests for PLAN-0099 W1-T03 — orchestrator-level phase timing emission.

Asserts that running the orchestrator end-to-end (mocked pipeline) produces:

  * a ``chat_phase_timings_ms`` structlog event with the expected phase
    keys present;
  * a terminal SSE ``done`` event whose ``data.phase_timings_ms`` carries
    the same per-phase breakdown so the chat-eval harness can scrape it
    from artifact frames.

Two paths are covered:

  * cache-hit path: a smaller breakdown (``check_cache`` only) is logged
    and execution short-circuits before the agent loop.
  * full agent-loop path: a single-iteration tool-use turn populates
    all major phases (planning, tool-execution, synthesis, persist).

Mocks borrow the same harness shape from
``test_chat_orchestrator_observability.py`` so the orchestrator's test
contract is not drifted.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import structlog.testing

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000001"


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.content = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str = "get_price_history", inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"ticker": "AAPL"}
    block.id = f"call_{name}"
    block.tool_use_id = block.id
    return block


def _make_retrieved_item() -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:price_history:AAPL"
    item.text = "AAPL price history..."
    item.score = 0.9
    return item


def _make_pipeline(
    first_llm_response: Any = None,
    cache_value: dict | None = None,
    stream_chunks: list[str] | None = None,
) -> MagicMock:
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=cache_value)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("test prompt", [], "ctx block"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(return_value=("Final answer.", []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.chat_with_tools = AsyncMock(
        return_value=first_llm_response or _make_llm_tool_response(text="Direct.")
    )
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
    # CRITICAL: route the real SSEEmitter.emit_done so the test verifies that
    # the orchestrator passes ``phase_timings_ms=...`` through. A blanket
    # MagicMock would swallow the kwarg and let a regression slip.
    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    _real_emitter = SSEEmitter()
    pipeline.emitter.emit_done = MagicMock(side_effect=_real_emitter.emit_done)
    pipeline.emitter.emit_final_answer = MagicMock(
        side_effect=lambda t: {"event": "final_answer", "data": json.dumps({"text": t})}
    )
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
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What is AAPL's revenue?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


def _make_tool_executor_mock(return_items: list, tool_defs: list | None = None) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools")
    registry.to_tool_definitions = MagicMock(return_value=tool_defs or [])
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    executor.last_per_tool_latencies_s = [0.05]
    return executor


def _make_factory_mock(executor: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


async def _collect(orch: Any, request: Any, uow: Any) -> tuple[list, list[dict]]:
    events: list = []
    with structlog.testing.capture_logs() as cap_logs:
        async for ev in orch.execute_streaming(request, uow):
            events.append(ev)
    return events, list(cap_logs)


# ── Cache-hit fast path ────────────────────────────────────────────────────


def test_cache_hit_emits_phase_timings_log() -> None:
    """A completion-cache hit logs ``chat_phase_timings_ms`` with ``cache_hit=True``."""
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    pipeline = _make_pipeline(cache_value={"answer": "cached", "citations": []})
    orch = ChatOrchestratorUseCase(pipeline=pipeline)
    request = _make_chat_request()
    uow = MagicMock()

    _events, logs = asyncio.run(_collect(orch, request, uow))
    matches = [r for r in logs if r.get("event") == "chat_phase_timings_ms"]
    assert matches, f"missing chat_phase_timings_ms; got: {[r.get('event') for r in logs]}"
    rec = matches[0]
    assert rec.get("cache_hit") is True
    assert "check_cache" in rec["phases"]
    assert rec["phases"]["check_cache"] >= 0.0


# ── Full agent-loop path ────────────────────────────────────────────────────


def test_full_loop_emits_phase_timings_log_and_sse_payload() -> None:
    """A single-iteration tool-use turn populates the expected phase keys.

    Validates BOTH:
      (a) the ``chat_phase_timings_ms`` structlog event carries the phase dict;
      (b) the terminal SSE ``done`` event's ``data.phase_timings_ms`` carries
          the same dict (the chat-eval harness scrapes this).
    """
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    tool_block = _make_tool_use_block("get_price_history")
    # iter-0 = tool call; iter-1 = direct text → break out of loop and into
    # second-turn streaming via the final stream_chat path (had_tool_calls=True
    # and direct_text is empty in iter-1).
    call_count = [0]

    async def _two_call_llm(messages, tools=None, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_llm_tool_response(tool_calls=[tool_block])
        # iter-1 with empty text → fall through to final stream_chat synthesis.
        return _make_llm_tool_response(text="", tool_calls=[])

    pipeline = _make_pipeline()
    pipeline.llm_chain.chat_with_tools = _two_call_llm

    executor = _make_tool_executor_mock([_make_retrieved_item()])
    factory = _make_factory_mock(executor)

    orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
    request = _make_chat_request()
    uow = MagicMock()

    events, logs = asyncio.run(_collect(orch, request, uow))

    # (a) structlog event.
    timing_logs = [r for r in logs if r.get("event") == "chat_phase_timings_ms"]
    assert timing_logs, f"missing chat_phase_timings_ms event; got {[r.get('event') for r in logs]}"
    rec = timing_logs[-1]
    phases = rec["phases"]
    # Required keys for the full path.
    for required in (
        "check_cache",
        "validate_input",
        "load_history",
        "entity_resolution",
        "llm_tool_planning",
        "tool_execution",
        "llm_synthesis_streaming",
        "persist_and_cache",
    ):
        assert required in phases, f"phase {required} missing from breakdown: {phases.keys()}"
    assert rec["total_ms"] >= 0
    assert rec["provider"] == "deepinfra"

    # (b) SSE done payload.
    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, "no done SSE event emitted"
    done_payload = json.loads(done_events[-1]["data"])
    assert done_payload["type"] == "done"
    assert "phase_timings_ms" in done_payload
    sse_phases = done_payload["phase_timings_ms"]
    # SSE payload must match the structlog snapshot key-for-key.
    assert set(sse_phases.keys()) == set(phases.keys())
