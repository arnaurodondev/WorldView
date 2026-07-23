"""Unit regression tests for ``effective_thread_id`` resolution (2026-07-23 fix).

Companion to the DB-backed integration test
``tests/integration/test_thread_user_attribution_e2e.py`` (which proves the fix
end-to-end against a real Postgres). These lightweight, DB-free unit tests lock
in the exact behaviour of the one-line resolution
(``effective_thread_id = request.thread_id or _turn_id`` in
``ChatOrchestratorUseCase.execute_streaming``) that the integration test cannot
cheaply cover on every PR:

1. **Continuing conversation** (``request.thread_id`` already set by the
   client) — the SAME id must reach every LLM cost-attribution call site AND
   the final ``persist_chat`` call, UNCHANGED. This guards against a future
   regression such as accidentally swapping the ternary to
   ``_turn_id or request.thread_id`` (which would silently overwrite a
   client-supplied thread_id with a fresh one every turn) — a one-line typo
   that would not be caught by the existing e2e test, since every fixture in
   the codebase's other orchestrator tests constructs ``ChatRequest`` with
   ``thread_id=None`` (per the code-review finding that flagged this gap).
2. **New conversation** (``request.thread_id is None``) — a single
   NON-none id must be generated and reused consistently across every call
   site and the persist step (the literal 2026-07-23 audit finding).

Reuses the proven pipeline/request fixture helpers from
``test_chat_orchestrator_fallback.py`` (same sys.path-insert import pattern
already used by ``test_chat_orchestrator_second_turn.py`` — this test tree has
no ``__init__.py`` so neither absolute nor relative package imports resolve).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

sys.path.insert(0, str(Path(__file__).parent))
from test_chat_orchestrator_fallback import (
    _FAKE_UUID,
    _collect_events,
    _make_factory_with_execute_side_effect,
    _make_llm_tool_response,
    _make_pipeline,
    _make_retrieved_item,
    _make_tool_use_block,
)


def _make_request(thread_id: UUID | None) -> Any:
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What's the latest news on MSTR?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=thread_id,
    )


def _wire_capturing_llm_chain(pipeline: Any) -> tuple[list[Any], list[Any]]:
    """Wrap the fixture's ``chat_with_tools``/``stream_chat`` to record the
    ``thread_id`` kwarg each call receives, without changing their behaviour.
    """
    tool_call_thread_ids: list[Any] = []
    stream_thread_ids: list[Any] = []

    _orig_chat_with_tools = pipeline.llm_chain.chat_with_tools
    _orig_stream_chat = pipeline.llm_chain.stream_chat

    async def _capturing_chat_with_tools(*args: Any, **kwargs: Any) -> Any:
        tool_call_thread_ids.append(kwargs.get("thread_id"))
        return await _orig_chat_with_tools(*args, **kwargs)

    async def _capturing_stream_chat(*args: Any, **kwargs: Any):
        stream_thread_ids.append(kwargs.get("thread_id"))
        async for chunk in _orig_stream_chat(*args, **kwargs):
            yield chunk

    pipeline.llm_chain.chat_with_tools = _capturing_chat_with_tools
    pipeline.llm_chain.stream_chat = _capturing_stream_chat
    return tool_call_thread_ids, stream_thread_ids


class TestContinuingConversationPreservesClientThreadId:
    def test_client_supplied_thread_id_reaches_every_llm_call_and_persist(self) -> None:
        """``request.thread_id`` is already set (continuing conversation) — the
        SAME value must reach chat_with_tools, stream_chat, AND persist_chat,
        completely unchanged (never replaced by a freshly-generated id).
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        client_thread_id = uuid4()
        # Iteration 0 requests one tool call (so the loop executes a tool AND
        # goes on to the stream_chat synthesis turn — a no-tool-call response
        # short-circuits straight to the raw text, never touching stream_chat,
        # per ``llm_answered_without_tools``/``llm_direct_text_generation``).
        # Iteration 1 stops requesting tools, ending the loop.
        tool_response = _make_llm_tool_response(
            text=None, tool_calls=[_make_tool_use_block("search_documents", {"query": "test"})]
        )
        direct_response = _make_llm_tool_response(text="Direct answer.", tool_calls=[])
        pipeline = _make_pipeline(tool_response)
        pipeline.llm_chain.chat_with_tools = AsyncMock(side_effect=[tool_response, direct_response])
        tool_call_ids, stream_ids = _wire_capturing_llm_chain(pipeline)

        item = _make_retrieved_item()
        factory = _make_factory_with_execute_side_effect(execute_all_return=[item], execute_side_effects=[item])
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)

        request = _make_request(thread_id=client_thread_id)
        uow = AsyncMock()

        asyncio.run(_collect_events(orch, request, uow))

        assert tool_call_ids, "chat_with_tools was never called"
        assert all(
            tid == client_thread_id for tid in tool_call_ids
        ), f"chat_with_tools received a DIFFERENT thread_id than the client supplied: {tool_call_ids}"
        assert stream_ids, "stream_chat was never called"
        assert all(
            tid == client_thread_id for tid in stream_ids
        ), f"stream_chat received a DIFFERENT thread_id than the client supplied: {stream_ids}"

        # persist_chat must ALSO receive the exact same client-supplied id —
        # never overwritten by a freshly-generated one.
        pipeline.persist_chat.assert_awaited_once()
        assert pipeline.persist_chat.await_args.kwargs["thread_id"] == client_thread_id


class TestNewConversationResolvesConsistentThreadId:
    def test_none_thread_id_resolves_to_one_consistent_non_none_id(self) -> None:
        """``request.thread_id is None`` (new conversation) — a single non-None
        id must be minted and reused identically across every LLM call site
        AND the persist step. This is the literal 2026-07-23 audit regression:
        before the fix, LLM calls saw ``None`` all turn while persist minted a
        SECOND, different id at the very end.
        """
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        llm_response = _make_llm_tool_response(text="Direct answer.", tool_calls=[])
        pipeline = _make_pipeline(llm_response)
        tool_call_ids, stream_ids = _wire_capturing_llm_chain(pipeline)

        factory = _make_factory_with_execute_side_effect(execute_all_return=[], execute_side_effects=[])
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)

        request = _make_request(thread_id=None)
        uow = AsyncMock()

        asyncio.run(_collect_events(orch, request, uow))

        all_ids = {*tool_call_ids, *stream_ids}
        assert (
            None not in all_ids
        ), f"a NULL thread_id reached an LLM call: tool_call={tool_call_ids} stream={stream_ids}"
        assert len(all_ids) == 1, f"expected ONE consistent resolved id across the whole turn, got: {all_ids}"
        resolved_id = next(iter(all_ids))

        pipeline.persist_chat.assert_awaited_once()
        assert pipeline.persist_chat.await_args.kwargs["thread_id"] == resolved_id, (
            "persist_chat used a DIFFERENT id than the one seen by the LLM calls this turn "
            "(the exact 2026-07-23 regression)"
        )
