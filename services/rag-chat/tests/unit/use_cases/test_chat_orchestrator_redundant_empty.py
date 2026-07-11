"""Unit tests for the C5 redundant-empty terminal guard (FINAL-67 efficiency).

The agent's dominant inefficiency was re-emitting the SAME (tool, args) call
after it returned EMPTY — search_documents 4-6x, get_portfolio_context no-arg
3-5x — burning iterations and ending in a refusal. The orchestrator now records
the exact (tool, args) signature of every cleanly-empty result and, when a whole
incoming batch consists only of those already-empty re-calls, skips re-executing
them and nudges the LLM to switch tools / answer.

These tests reuse the tool-loop mock harness to drive the real loop and assert
that the executor is NOT invoked a second time for an identical empty call. The
guard fires on the MIXED-batch case the existing all-tools-empty branch misses:
iteration 0 retrieves a non-empty sibling (so the loop continues), iteration 1
re-emits ONLY the already-empty call.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the established harness helpers from the tool-loop test module.
# Import by bare module name (NOT ``tests.unit.use_cases....``): this package has
# no ``__init__.py`` files under ``tests/``, so pytest's default ``prepend`` import
# mode inserts the test file's own directory onto ``sys.path`` and imports each
# module by its top-level name. A ``tests.``-qualified import raises
# ``ModuleNotFoundError: No module named 'tests'`` at collection time, which aborts
# the entire session (both the unit and integration CI jobs). Keep this bare.
from test_chat_orchestrator_tool_loop import (
    _FAKE_UUID,
    _collect_events,
    _make_chat_request,
    _make_factory_mock,
    _make_llm_tool_response,
    _make_pipeline,
    _make_retrieved_item,
    _make_tool_executor_mock,
    _make_tool_use_block,
)

pytestmark = pytest.mark.unit


def _executor_by_tool_name(result_map: dict[str, list]) -> MagicMock:
    """Build an executor whose execute_all returns per-call results by tool name.

    ``result_map`` maps a tool name -> the (possibly empty) item list that call
    should return. execute_all receives the list of fresh ToolUseBlocks in order
    and must return one entry per block, so we look each up by ``block.name``.
    """
    executor = _make_tool_executor_mock([])

    async def _execute_all(blocks: list) -> list:
        return [result_map.get(b.name, []) for b in blocks]

    executor.execute_all = AsyncMock(side_effect=_execute_all)
    # The single-tool empty-result fallback path calls executor.execute(); return
    # empty so the fallback finds nothing and the loop proceeds normally.
    executor.execute = AsyncMock(return_value=[])
    return executor


def test_redundant_empty_call_not_re_executed() -> None:
    """An identical empty (tool, args) re-call is short-circuited, not re-run.

    iter-0: [search_documents(X)->empty, get_price_history->rows] -> loop continues
            (a sibling returned data, so neither all-empty nor all-failed fires).
    iter-1: [search_documents(X)] alone -> already-empty, guard intercepts.
    iter-2: direct answer -> loop ends.

    The duplicate empty search must NOT reach execute_all again.
    """
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    empty_call = _make_tool_use_block("search_documents", inp={"query": "mstr dec 2024 news"})
    good_call = _make_tool_use_block("get_price_history", inp={"ticker": "MSTR"})

    seen_search_blocks = [0]

    async def _llm(messages: list, tools: Any = None, **kwargs: Any) -> MagicMock:
        # Count how many times execute_all was asked to run the empty search.
        if seen_search_blocks[0] == 0:
            seen_search_blocks[0] = 1
            return _make_llm_tool_response(tool_calls=[empty_call, good_call])
        if seen_search_blocks[0] == 1:
            seen_search_blocks[0] = 2
            return _make_llm_tool_response(tool_calls=[empty_call])
        return _make_llm_tool_response(text="No December 2024 news was found for MSTR.", tool_calls=[])

    pipeline = _make_pipeline()
    pipeline.llm_chain.chat_with_tools = _llm

    executor = _executor_by_tool_name({"search_documents": [], "get_price_history": [_make_retrieved_item()]})
    factory = _make_factory_mock(executor)

    orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
    request = _make_chat_request()
    uow = MagicMock()

    asyncio.run(_collect_events(orch, request, uow))

    # Count how many ToolUseBlocks for search_documents were actually executed.
    executed_search = 0
    for call in executor.execute_all.call_args_list:
        blocks = call.args[0] if call.args else call.kwargs.get("blocks", [])
        executed_search += sum(1 for b in blocks if b.name == "search_documents")

    # The empty search_documents ran ONCE (iter-0); the iter-1 duplicate was
    # intercepted by the redundant-empty guard.
    assert executed_search == 1


def test_distinct_call_after_empty_still_executes() -> None:
    """A genuinely DIFFERENT call after an empty one is still executed.

    The guard only fires when EVERY call in the batch is an already-empty
    re-call; a fresh, distinct call must run normally.
    """
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    empty_call = _make_tool_use_block("search_documents", inp={"query": "first query"})
    good_call = _make_tool_use_block("get_price_history", inp={"ticker": "MSTR"})
    distinct_call = _make_tool_use_block("get_entity_news", inp={"entity_id": _FAKE_UUID})

    step = [0]

    async def _llm(messages: list, tools: Any = None, **kwargs: Any) -> MagicMock:
        step[0] += 1
        if step[0] == 1:
            return _make_llm_tool_response(tool_calls=[empty_call, good_call])
        if step[0] == 2:
            return _make_llm_tool_response(tool_calls=[distinct_call])
        return _make_llm_tool_response(text="Here is the news.", tool_calls=[])

    pipeline = _make_pipeline()
    pipeline.llm_chain.chat_with_tools = _llm

    executor = _executor_by_tool_name(
        {
            "search_documents": [],
            "get_price_history": [_make_retrieved_item()],
            "get_entity_news": [_make_retrieved_item()],
        }
    )
    factory = _make_factory_mock(executor)

    orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
    request = _make_chat_request()
    uow = MagicMock()

    asyncio.run(_collect_events(orch, request, uow))

    # The distinct get_entity_news call must have been executed (guard did NOT
    # swallow the batch because the call was fresh, not already-empty).
    executed_news = 0
    for call in executor.execute_all.call_args_list:
        blocks = call.args[0] if call.args else call.kwargs.get("blocks", [])
        executed_news += sum(1 for b in blocks if b.name == "get_entity_news")
    assert executed_news == 1
