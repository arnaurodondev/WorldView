"""Integration tests for the tool-use path in ChatOrchestratorUseCase.

These tests mock the LLM (chat_with_tools returns predefined LLMToolResponse objects)
and the S6/S7/S1 port adapters to verify that the orchestrator wires everything
correctly without requiring PostgreSQL or any live upstream service.

WHY integration (not unit): the tests exercise the full pipeline collaboration
between ChatOrchestratorUseCase, ChatPipeline, ToolExecutorFactory, and
SSEEmitter. Unit tests in tests/unit/ cover individual components in isolation;
these tests verify the cross-component wiring.

Test matrix:
  test_factual_query_calls_search_documents   — LLM calls search_documents; second turn runs
  test_relationship_query_calls_graph_tool    — LLM calls get_entity_graph; items produced
  test_temporal_query_calls_price_history     — LLM calls get_price_history; items produced
  test_portfolio_query_calls_portfolio_tool   — LLM calls get_portfolio_context; items produced
  test_all_tools_failed_returns_graceful_answer — all tools return None/[]; error emitted; no second turn
  test_no_tool_calls_direct_answer            — LLM returns text directly; token emitted without tools

pytest.mark.integration: requires rag-chat package on PYTHONPATH but NOT PostgreSQL.

NOTE: This module overrides the _clean_tables autouse fixture from the integration
conftest.py (which requires a live DB) to a no-op. These tests mock all infrastructure
dependencies so PostgreSQL is NOT required — they run in any environment.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


# ── Override the DB-requiring autouse fixture from integration/conftest.py ────
# The parent conftest defines _clean_tables(db_engine) which skips when Postgres
# is not available. Since these tests use no DB, we override it here to a no-op
# so they run in any environment (CI, local without docker).
@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncGenerator[None, None]:  # type: ignore[override]
    """No-op override: tool-use orchestrator tests do not use the database."""
    yield


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_chat_request(message: str = "What risks does Apple mention in their 10-K?"):
    """Build a minimal ChatRequest for tests.

    tenant_id and user_id are random UUIDs so tests are isolated.
    thread_id=None means no conversation history to load from DB.
    """
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message=message,
        context=ChatContext(entity_ids=(), date_range=None),
        tenant_id=uuid4(),
        user_id=uuid4(),
        thread_id=None,  # no DB history lookup needed
    )


def _make_retrieved_item(tool_name: str = "search_documents") -> Any:
    """Build a minimal RetrievedItem with a valid fusion_score (score*recency*trust)."""
    from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
    from rag_chat.domain.enums import ItemType

    # RetrievedItem.create() computes recency_score and fusion_score automatically.
    return RetrievedItem.create(
        item_id=f"test:{tool_name}:item-001",
        item_type=ItemType.chunk,
        text=f"Test content from {tool_name}",
        score=0.85,
        trust_weight=0.80,
        citation_meta=CitationMeta(
            title="Test document",
            url="https://example.com",
            source_name="test",
            published_at=None,
            entity_name=None,
        ),
    )


def _make_tool_response_with_calls(tool_name: str, tool_input: dict | None = None):
    """Build an LLMToolResponse that requests one tool call.

    This simulates the first LLM turn returning finish_reason="tool_calls"
    with a single tool_use block. The LOCAL ToolUseBlock (tool_executor.py)
    uses tool_use_id; we match that variant here since the orchestrator reads
    llm_response.tool_calls and dispatches via ToolExecutor.execute().
    """
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock as LocalToolUseBlock

    tool_block = LocalToolUseBlock(
        name=tool_name,
        input=tool_input or {"query": "test query"},
        tool_use_id="call-test-001",
    )
    # LLMToolResponse wraps the LOCAL ToolUseBlock in its tool_calls list.
    # The orchestrator reads llm_response.tool_calls via getattr() so any object
    # with a .tool_calls attribute works — we use a MagicMock for simplicity.
    response = MagicMock()
    response.tool_calls = [tool_block]
    response.text = None
    response.finish_reason = "tool_calls"
    return response


def _make_tool_response_direct_answer(text: str = "Apple mentions supply chain risk."):
    """Build an LLMToolResponse with finish_reason='stop' and no tool calls.

    This simulates the LLM answering directly from training knowledge without
    requesting any tools.
    """
    response = MagicMock()
    response.tool_calls = []
    response.text = text
    response.finish_reason = "stop"
    return response


def _build_pipeline_mock(llm_response: Any, stream_text: str = "Final answer text."):
    """Build a heavily mocked ChatPipeline that bypasses all real I/O.

    WHY mock every pipeline step: the integration tests focus on the orchestrator
    wiring, not on individual collaborators. Mocking at the pipeline level keeps
    tests fast and PostgreSQL-free while still exercising the full
    ChatOrchestratorUseCase control flow.

    Returns (pipeline_mock, llm_chain_mock) so callers can assert on llm_chain.
    """
    pipeline = MagicMock()

    # Step 0: validate_input — return message unchanged
    pipeline.validate_input = AsyncMock(side_effect=lambda msg: msg)

    # Step 1: check_cache — always miss (None) so the full pipeline runs
    pipeline.check_cache = AsyncMock(return_value=None)

    # Step 2: check_rate_limit — no-op (not rate limited in tests)
    pipeline.check_rate_limit = AsyncMock(return_value=None)

    # Step 3: load_history — return empty list (no thread history)
    pipeline.load_history = AsyncMock(return_value=[])

    # Step 4: resolve_entities — return empty list (no entities to resolve)
    pipeline.resolve_entities = AsyncMock(return_value=[])

    # Step 8b: rerank_items — return items unchanged (identity reranker)
    pipeline.rerank_items = AsyncMock(side_effect=lambda _query, items: items)

    # build_prompt — return (prompt_str, [], context_block) tuple
    # The orchestrator reads [2] for context_block to inject into messages.
    pipeline.build_prompt = MagicMock(return_value=("Test system prompt", [], "Context block from tools"))

    # process_output — return (answer_text, []) with no citations
    pipeline.process_output = MagicMock(return_value=(stream_text, []))

    # Step 10: persist_chat — async, returns (user_msg_id, asst_msg_id) tuple
    # The orchestrator unpacks this as `_user_msg_id, asst_msg_id = await p.persist_chat(...)`
    _fake_user_msg_id = uuid4()
    _fake_asst_msg_id = uuid4()
    pipeline.persist_chat = AsyncMock(return_value=(_fake_user_msg_id, _fake_asst_msg_id))

    # Step 10b: write_completion_cache — async no-op
    pipeline.write_completion_cache = AsyncMock(return_value=None)

    # persistence.save_interaction — async no-op (used by older path; kept for safety)
    pipeline.persistence = MagicMock()
    pipeline.persistence.save_interaction = AsyncMock(return_value=None)

    # ── LLM chain mock ────────────────────────────────────────────────────────
    llm_chain = MagicMock()
    llm_chain.last_provider_name = "test_provider"

    # chat_with_tools: returns the pre-defined LLMToolResponse (non-streaming first turn)
    llm_chain.chat_with_tools = AsyncMock(return_value=llm_response)

    # stream_chat: yields a single chunk for the second turn answer
    async def _stream_gen(*_args, **_kwargs):
        yield stream_text

    llm_chain.stream_chat = MagicMock(side_effect=_stream_gen)

    pipeline.llm_chain = llm_chain

    # SSEEmitter: use the real emitter so events are genuine dicts
    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()

    return pipeline, llm_chain


def _build_tool_executor_factory_mock(tool_name: str, tool_result: Any):
    """Build a mocked ToolExecutorFactory that returns a per-request executor.

    The per-request executor's execute() returns tool_result for any tool_call.
    execute_all() wraps execute() in a list — one item per tool call.

    Args:
        tool_name: Informational only — the mock responds to any tool_call.
        tool_result: What execute() returns. May be:
            - A RetrievedItem (single-result tool)
            - A list[RetrievedItem] (multi-result tool like search_documents)
            - None (tool failure / all-tools-failed scenario)
    """
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=tool_result)

    # execute_all mirrors real ToolExecutor.execute_all: returns list of results
    async def _execute_all(tool_calls):
        return [await executor.execute(tc) for tc in tool_calls]

    executor.execute_all = AsyncMock(side_effect=_execute_all)

    # Registry must have to_system_prompt_section() and optionally to_tool_definitions()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="[Tool manifest]")
    registry.to_tool_definitions = MagicMock(return_value=[])
    executor._registry = registry

    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)

    return factory, executor


async def _collect_events(request, pipeline, factory) -> list[dict]:  # type: ignore[type-arg]
    """Run execute_streaming and collect all yielded SSE event dicts.

    WHY list: the orchestrator is an async generator. We consume it fully
    so all side effects (tool execution, LLM calls, persistence) have run.
    """
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    orchestrator = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)

    events = []
    async for event in orchestrator.execute_streaming(request, uow):
        events.append(event)
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factual_query_calls_search_documents():
    """LLM requests search_documents; orchestrator executes it and calls second turn.

    Assertions:
    1. A tool_call SSE event is emitted with tool_name="search_documents"
    2. A token SSE event is emitted (second LLM turn ran and streamed text)
    3. ToolExecutorFactory.for_request() was called once (per-request executor)
    4. executor.execute_all() was called with the tool_call block
    """
    retrieved_item = _make_retrieved_item("search_documents")
    llm_response = _make_tool_response_with_calls("search_documents", {"query": "Apple 10-K risk factors"})
    pipeline, _llm_chain = _build_pipeline_mock(llm_response)
    factory, executor = _build_tool_executor_factory_mock("search_documents", [retrieved_item])

    request = _make_chat_request("What risks does Apple mention in their latest 10-K?")
    events = await _collect_events(request, pipeline, factory)

    # SSEEmitter uses the "event" key (not "type") — values are "tool_call", "token", etc.
    # The "data" field is a JSON-encoded string with the "type" sub-field for some events.
    event_names = [e.get("event") for e in events]

    # Assert: tool_call event emitted (frontend spinner feedback)
    assert "tool_call" in event_names, f"Expected 'tool_call' event, got: {event_names}"

    # Assert: token event emitted (second LLM turn produced an answer)
    assert "token" in event_names, f"Expected 'token' event, got: {event_names}"

    # Assert: factory was asked for a per-request executor
    factory.for_request.assert_called_once()

    # Assert: execute_all called (tool call was dispatched)
    executor.execute_all.assert_called_once()


@pytest.mark.asyncio
async def test_relationship_query_calls_graph_tool():
    """LLM requests get_entity_graph; orchestrator executes it and streams answer.

    Verifies graph-type queries route through the entity graph tool and produce
    a tool_result event indicating success.
    """
    retrieved_item = _make_retrieved_item("get_entity_graph")
    llm_response = _make_tool_response_with_calls("get_entity_graph", {"entity_name": "Apple Inc", "depth": 1})
    pipeline, llm_chain = _build_pipeline_mock(llm_response)
    factory, _executor = _build_tool_executor_factory_mock("get_entity_graph", [retrieved_item])

    request = _make_chat_request("Who are Apple's main subsidiaries and board members?")
    events = await _collect_events(request, pipeline, factory)

    event_names = [e.get("event") for e in events]

    # tool_call and tool_result events must both be present
    assert "tool_call" in event_names, f"Expected 'tool_call' event, got: {event_names}"
    assert "tool_result" in event_names, f"Expected 'tool_result' event, got: {event_names}"

    # Second LLM turn must have been called (stream_chat)
    llm_chain.stream_chat.assert_called_once()


@pytest.mark.asyncio
async def test_temporal_query_calls_price_history():
    """LLM requests get_price_history; orchestrator dispatches it.

    Price history queries are temporal — the tool returns a single RetrievedItem
    (not a list). Verifies the orchestrator handles single-item returns correctly.
    """
    # get_price_history returns a single RetrievedItem (not a list)
    retrieved_item = _make_retrieved_item("get_price_history")
    llm_response = _make_tool_response_with_calls(
        "get_price_history",
        {"ticker": "AAPL", "from_date": "2025-02-01", "to_date": "2025-05-01"},
    )
    pipeline, _llm_chain = _build_pipeline_mock(llm_response)
    # Return a single item (not list) — orchestrator must handle both variants
    factory, executor = _build_tool_executor_factory_mock("get_price_history", retrieved_item)

    request = _make_chat_request("What is AAPL's stock price trend over the last 3 months?")
    events = await _collect_events(request, pipeline, factory)

    event_names = [e.get("event") for e in events]
    assert "tool_call" in event_names, f"Expected 'tool_call' event, got: {event_names}"
    assert "token" in event_names, f"Expected 'token' event (second turn), got: {event_names}"

    # Verify the executor was called
    executor.execute_all.assert_called_once()


@pytest.mark.asyncio
async def test_portfolio_query_calls_portfolio_tool():
    """LLM requests get_portfolio_context; orchestrator executes it.

    Portfolio queries require user authentication (user_id set on request).
    Verifies the tool produces a RetrievedItem and the orchestrator proceeds
    to the second LLM turn.
    """
    retrieved_item = _make_retrieved_item("get_portfolio_context")
    llm_response = _make_tool_response_with_calls("get_portfolio_context", {})
    pipeline, _llm_chain = _build_pipeline_mock(llm_response)
    factory, _executor = _build_tool_executor_factory_mock("get_portfolio_context", [retrieved_item])

    request = _make_chat_request("How is my portfolio performing today?")
    events = await _collect_events(request, pipeline, factory)

    event_names = [e.get("event") for e in events]
    assert "tool_call" in event_names, f"Expected 'tool_call' event, got: {event_names}"

    # Second turn must have run (we got tool results to answer from)
    assert "token" in event_names, f"Expected 'token' event after portfolio lookup, got: {event_names}"


@pytest.mark.asyncio
async def test_all_tools_failed_returns_graceful_answer():
    """All tool executions return None/empty; orchestrator emits error, skips second turn.

    This is the all-tools-failed guard (step 7 in the pipeline docstring).
    Without this guard, the LLM would produce hallucinated answers from empty context.
    The orchestrator MUST NOT call stream_chat if no tool returned data.

    Assertions:
    1. An 'error' SSE event is emitted (not a 'token' event)
    2. stream_chat is NOT called (no second LLM turn)
    3. The error event carries code="all_tools_failed"
    """
    # All tools return None (network failure / no matching data)
    llm_response = _make_tool_response_with_calls("search_documents", {"query": "Apple risks"})
    pipeline, llm_chain = _build_pipeline_mock(llm_response)
    factory, _executor = _build_tool_executor_factory_mock("search_documents", None)

    request = _make_chat_request("What risks does Apple mention?")
    events = await _collect_events(request, pipeline, factory)

    event_names = [e.get("event") for e in events]

    # Error event must be emitted
    assert "error" in event_names, f"Expected 'error' event on all-tools-failed, got: {event_names}"

    # No token event — second turn must NOT have been called
    assert "token" not in event_names, f"Did NOT expect 'token' event when all tools failed, got: {event_names}"

    # Verify stream_chat was never called (hallucination guard enforced)
    llm_chain.stream_chat.assert_not_called()

    # The error event carries the code inside the JSON-encoded "data" field.
    # SSEEmitter.emit_error() returns {"event": "error", "data": json.dumps({"code": ..., "message": ...})}
    error_events = [e for e in events if e.get("event") == "error"]
    assert any(
        json.loads(e.get("data", "{}")).get("code") == "all_tools_failed" for e in error_events
    ), f"Expected error code='all_tools_failed' in data, got: {error_events}"


@pytest.mark.asyncio
async def test_no_tool_calls_direct_answer():
    """LLM returns text directly (finish_reason='stop'); orchestrator emits token immediately.

    When the LLM decides it can answer without tools (e.g. a general knowledge
    question), it returns text and an empty tool_calls list. The orchestrator
    skips tool execution entirely and emits the text as a token event.

    Assertions:
    1. A 'token' event is emitted with the LLM text
    2. No 'tool_call' event is emitted (no tools were requested)
    3. execute_all is NOT called
    """
    direct_text = "Apple is a technology company headquartered in Cupertino, CA."
    llm_response = _make_tool_response_direct_answer(direct_text)
    pipeline, _llm_chain = _build_pipeline_mock(llm_response, stream_text=direct_text)
    factory, executor = _build_tool_executor_factory_mock("search_documents", None)

    request = _make_chat_request("What is Apple?")
    events = await _collect_events(request, pipeline, factory)

    event_names = [e.get("event") for e in events]

    # A token event must be emitted with the direct answer text
    assert "token" in event_names, f"Expected 'token' event for direct LLM answer, got: {event_names}"

    # No tool_call event — the LLM made no tool requests
    assert "tool_call" not in event_names, f"Did NOT expect 'tool_call' event for direct answer, got: {event_names}"

    # execute_all must NOT have been called
    executor.execute_all.assert_not_called()
