"""Unit tests for FIX-LIVE-E multi-tool fallback chain in ChatOrchestratorUseCase.

Verifies:
  - Per (failed_tool, alt_tool) arg projection (drops bad keys, injects entity_id)
  - Fallback chain walks alts in order, stops at first hit
  - Projection returning None skips the alt
  - SSE tool_call event for fallback carries is_fallback=True + fallback_of=<name>
  - SSE tool_result event always fires after fallback attempt
  - When fallback recovers items, _all_failed flips and pipeline continues
  - When fallback chain exhausts, original all_tools_failed error still emitted

Cite: docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md
      FIX-LIVE-E section; Phase 5c Q2 (MSTR news) USELESS verdict.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Tests: arg-projection functions (pure unit, no orchestrator wiring)
# ---------------------------------------------------------------------------


class TestFallbackArgProjection:
    """Direct unit tests for the per-pair projection functions."""

    def test_search_documents_to_entity_intelligence_with_ctx_returns_entity_id(self) -> None:
        """search_documents → get_entity_intelligence: drops date/source, injects entity_id from ctx."""
        from rag_chat.application.pipeline.tool_executor import EntityContext
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        ctx = EntityContext(
            entity_id=UUID("00000000-0000-0000-0000-000000000099"),
            ticker="MSTR",
            name="MicroStrategy",
        )
        failed_args = {
            "query": "MSTR news",
            "date_from": "2026-05-01",
            "date_to": "2026-05-24",
            "entity_tickers": ["MSTR"],
            "source_types": ["news"],
        }

        out = _build_fallback_args("search_documents", "get_entity_intelligence", failed_args, ctx)
        assert out is not None
        # Only entity_id key — all upstream filters dropped.
        assert set(out.keys()) == {"entity_id"}
        assert out["entity_id"] == "00000000-0000-0000-0000-000000000099"

    def test_search_documents_to_entity_intelligence_no_ctx_returns_none(self) -> None:
        """When EntityContext is absent, the projection returns None (signals skip)."""
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        out = _build_fallback_args("search_documents", "get_entity_intelligence", {"query": "open question"}, ctx=None)
        assert out is None

    def test_search_documents_to_search_claims_uses_ctx_name(self) -> None:
        """search_documents → search_claims preserves entity_name via ctx; drops date/source."""
        from rag_chat.application.pipeline.tool_executor import EntityContext
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        ctx = EntityContext(
            entity_id=UUID("00000000-0000-0000-0000-000000000099"),
            ticker="MSTR",
            name="MicroStrategy",
        )
        failed_args = {
            "query": "MSTR news",
            "entity_tickers": ["MSTR"],
            "date_from": "2026-05-01",
            "date_to": "2026-05-24",
        }

        out = _build_fallback_args("search_documents", "search_claims", failed_args, ctx)
        assert out is not None
        assert out == {"entity_name": "MicroStrategy"}

    def test_search_documents_to_search_claims_falls_back_to_ticker_when_no_ctx(self) -> None:
        """No ctx but entity_tickers present → use first ticker as entity_name."""
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        out = _build_fallback_args(
            "search_documents",
            "search_claims",
            {"query": "x", "entity_tickers": ["AAPL"]},
            ctx=None,
        )
        assert out is not None
        assert out == {"entity_name": "AAPL"}

    def test_search_documents_relaxed_drops_source_types_and_widens_dates(self) -> None:
        """Identity-shape relaxation: drops source_types, widens date window by 90d each side."""
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        out = _build_fallback_args(
            "search_documents",
            "search_documents",
            {
                "query": "MSTR news",
                "date_from": "2026-05-01",
                "date_to": "2026-05-24",
                "source_types": ["news"],
                "entity_tickers": ["MSTR"],
            },
            ctx=None,
        )
        assert out is not None
        assert "source_types" not in out  # dropped
        assert out["query"] == "MSTR news"  # preserved
        # Dates widened by 90 days each side.
        assert out["date_from"] == "2026-01-31"
        assert out["date_to"] == "2026-08-22"

    def test_unknown_pair_copies_verbatim(self) -> None:
        """When no projection is registered, args are copied verbatim (legacy behavior)."""
        from rag_chat.application.use_cases.chat_orchestrator import _build_fallback_args

        args = {"foo": "bar", "baz": 42}
        out = _build_fallback_args("some_tool", "unrelated_tool", args, ctx=None)
        assert out == args
        # Must be a copy (not the same reference), so mutations don't leak.
        assert out is not args


# ---------------------------------------------------------------------------
# Helpers (mirror test_chat_orchestrator_tool_loop.py for consistency)
# ---------------------------------------------------------------------------

_FAKE_UUID = "00000000-0000-0000-0000-000000000001"
_ENTITY_UUID = "00000000-0000-0000-0000-000000000099"


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str, inp: dict) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp
    block.tool_use_id = f"call_{name}"
    return block


def _make_retrieved_item(text: str = "Fallback item.") -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = f"tool:fallback:{text[:10]}"
    item.text = text
    item.score = 0.9
    item.source_id = None
    return item


def _make_pipeline(first_llm_response: Any, stream_chunks: list[str] | None = None) -> MagicMock:
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])

    # Provide a resolved entity so EntityContext is populated by the orchestrator.
    _resolved = MagicMock()
    _resolved.entity_id = UUID(_ENTITY_UUID)
    _resolved.ticker = "MSTR"
    _resolved.canonical_name = "MicroStrategy"
    _resolved.entity_type = "financial_instrument"
    pipeline.resolve_entities = AsyncMock(return_value=[_resolved])

    pipeline.build_prompt = MagicMock(return_value=("test prompt", [], "context block"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(return_value=("Final answer.", []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.chat_with_tools = AsyncMock(return_value=first_llm_response)
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    _chunks = stream_chunks or ["Final ", "answer."]

    async def _stream_chat(messages: list, **kwargs: Any):
        for chunk in _chunks:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    # SSE emitter — return realistic dicts; emit_tool_call captures kwargs so we can assert.
    pipeline.emitter = MagicMock()
    pipeline.emitter.emit_status = MagicMock(return_value={"event": "status", "data": "{}"})
    pipeline.emitter.emit_thinking = MagicMock(return_value={"event": "thinking", "data": "{}"})
    pipeline.emitter.emit_token = MagicMock(side_effect=lambda t: {"event": "token", "data": json.dumps({"text": t})})
    pipeline.emitter.emit_citations = MagicMock(return_value={"event": "citations", "data": "[]"})
    pipeline.emitter.emit_contradictions = MagicMock(return_value={"event": "contradictions", "data": "[]"})
    pipeline.emitter.emit_metadata = MagicMock(return_value={"event": "metadata", "data": "{}"})
    pipeline.emitter.emit_done = MagicMock(return_value={"event": "done", "data": '{"type":"done"}'})

    # is_fallback flag is captured in the emitted dict so tests can read it back.
    def _emit_tool_call(
        name: str, inp: dict, status: str = "running", is_fallback: bool = False, fallback_of: str | None = None
    ) -> dict:
        payload: dict[str, Any] = {"tool": name, "input": inp, "status": status}
        if is_fallback:
            payload["is_fallback"] = True
            if fallback_of:
                payload["fallback_of"] = fallback_of
        return {"event": "tool_call", "data": json.dumps(payload)}

    pipeline.emitter.emit_tool_call = MagicMock(side_effect=_emit_tool_call)
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
        message="What's the latest news on MSTR?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


def _make_factory_with_execute_side_effect(execute_all_return: list, execute_side_effects: list) -> MagicMock:
    """Build a factory whose executor.execute_all returns one thing, then .execute returns alt results."""
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- search_documents")
    registry.to_tool_definitions = MagicMock(return_value=[])
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=execute_all_return)
    executor.execute = AsyncMock(side_effect=execute_side_effects)

    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


async def _collect_events(orch: Any, request: Any, uow: Any) -> list:
    events: list = []
    async for event in orch.execute_streaming(request, uow):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Tests: orchestrator-level fallback integration
# ---------------------------------------------------------------------------


class TestFallbackChainIntegration:
    def test_fallback_emits_tool_call_with_is_fallback_flag(self) -> None:
        """When primary search_documents returns empty, the fallback alt tool emits
        a tool_call event carrying is_fallback=True and fallback_of='search_documents'."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        # LLM emits one tool call (search_documents) on iteration 0; iteration 1
        # returns a direct text answer to terminate the loop after fallback succeeds.
        tool_block = _make_tool_use_block(
            "search_documents",
            {
                "query": "MSTR news",
                "date_from": "2026-05-01",
                "date_to": "2026-05-24",
                "entity_tickers": ["MSTR"],
                "source_types": ["news"],
            },
        )
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        second_resp = _make_llm_tool_response(text="Direct answer with the fallback data.")
        pipeline = _make_pipeline(first_llm_response=first_resp)
        pipeline.llm_chain.chat_with_tools = AsyncMock(side_effect=[first_resp, second_resp])

        # Primary returns empty list (counts as empty, not None → status='empty').
        # Fallback chain order: search_documents (relaxed) → search_claims → get_entity_intelligence.
        # We make the FIRST fallback alt (relaxed search_documents) succeed.
        fallback_item = _make_retrieved_item("MSTR Bitcoin acquisition update.")
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[]],  # primary empty
            execute_side_effects=[[fallback_item]],  # first fallback alt succeeds
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        # Find the fallback tool_call event.
        tool_call_events = [e for e in events if e.get("event") == "tool_call"]
        # First tool_call is the primary; second is the fallback retry.
        assert len(tool_call_events) >= 2
        fallback_data = json.loads(tool_call_events[1]["data"])
        assert fallback_data.get("is_fallback") is True
        assert fallback_data.get("fallback_of") == "search_documents"

    def test_fallback_recovery_prevents_all_tools_failed_error(self) -> None:
        """When the fallback chain recovers items, the orchestrator does NOT emit
        all_tools_failed and proceeds to a normal final answer."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block(
            "search_documents",
            {"query": "MSTR news", "entity_tickers": ["MSTR"]},
        )
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        second_resp = _make_llm_tool_response(text="Answer based on fallback.")
        pipeline = _make_pipeline(first_llm_response=first_resp)
        pipeline.llm_chain.chat_with_tools = AsyncMock(side_effect=[first_resp, second_resp])

        fallback_item = _make_retrieved_item("Useful narrative recovered.")
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[]],
            execute_side_effects=[[fallback_item]],
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        event_types = [e.get("event") for e in events]
        # all_tools_failed error must NOT be present.
        error_codes = [json.loads(e["data"]).get("code") for e in events if e.get("event") == "error"]
        assert "all_tools_failed" not in error_codes
        # Pipeline reaches the done event normally.
        assert "done" in event_types

    def test_fallback_chain_exhaustion_still_emits_all_tools_failed(self) -> None:
        """When EVERY alt also returns empty, the original all_tools_failed error is emitted."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block(
            "search_documents",
            {"query": "obscure topic", "entity_tickers": ["MSTR"]},
        )
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # All three alt attempts return empty.
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[]],
            execute_side_effects=[[], [], []],
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        error_codes = [json.loads(e["data"]).get("code") for e in events if e.get("event") == "error"]
        assert "all_tools_failed" in error_codes

    def test_fallback_tool_result_event_always_fires(self) -> None:
        """Every fallback tool_call MUST be paired with a tool_result event for UI close-signal."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("search_documents", {"query": "x", "entity_tickers": ["MSTR"]})
        first_resp = _make_llm_tool_response(tool_calls=[tool_block])
        pipeline = _make_pipeline(first_llm_response=first_resp)

        # All alts return empty so we see every fallback tool_call + tool_result pair.
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[]],
            execute_side_effects=[[], [], []],
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        fallback_tool_calls = [
            e for e in events if e.get("event") == "tool_call" and json.loads(e["data"]).get("is_fallback") is True
        ]
        # Each fallback attempt has a matching tool_result immediately after.
        # Count fallback tool_calls == count of tool_result events for fallback alts (>=1 each).
        assert len(fallback_tool_calls) >= 1
        # Verify total tool_result count matches primary (1) + fallbacks.
        tool_result_events = [e for e in events if e.get("event") == "tool_result"]
        assert len(tool_result_events) >= 1 + len(fallback_tool_calls)
