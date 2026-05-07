"""Unit tests for ChatPersistenceUseCase (T-F-4-01).

Tests that user + assistant messages are created with correct fields,
thread metadata is updated, and the UoW is committed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_THREAD_ID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.messages = MagicMock()
    uow.messages.create = AsyncMock(return_value=None)
    uow.threads = MagicMock()
    uow.threads.update_last_msg = AsyncMock(return_value=None)
    uow.commit = AsyncMock(return_value=None)
    return uow


def _make_assistant_response(
    content: str = "Here is the answer.",
    provider: str = "deepinfra",
    model: str = "deepseek-r1-distill-qwen-32b",
    token_count_in: int | None = 100,
    token_count_out: int | None = 50,
    latency_ms: int = 1200,
    resolved_entities: tuple = (),
    citations: tuple = (),
    contradiction_refs: tuple = (),
) -> object:
    from rag_chat.application.use_cases.persist_chat import AssistantResponse
    from rag_chat.domain.enums import QueryIntent

    return AssistantResponse(
        content=content,
        intent=QueryIntent.FINANCIAL_DATA,
        resolved_entities=resolved_entities,
        retrieval_plan=None,
        citations=citations,
        contradiction_refs=contradiction_refs,
        provider=provider,
        model=model,
        token_count_in=token_count_in,
        token_count_out=token_count_out,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatPersistenceUseCaseExecute:
    async def test_creates_two_messages(self) -> None:
        """Both user and assistant messages are created in the UoW."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response()

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="What is the P/E ratio?",
            assistant_response=resp,
            uow=uow,
        )

        assert uow.messages.create.call_count == 2

    async def test_returns_two_uuids(self) -> None:
        """Returns a tuple of (user_msg_id, assistant_msg_id)."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response()

        result = await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="How much is AAPL?",
            assistant_response=resp,
            uow=uow,
        )

        user_msg_id, asst_msg_id = result
        assert isinstance(user_msg_id, UUID)
        assert isinstance(asst_msg_id, UUID)
        assert user_msg_id != asst_msg_id

    async def test_user_message_content_matches_input(self) -> None:
        """The user message persisted contains the original query text."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase
        from rag_chat.domain.enums import MessageRole

        uow = _make_uow()
        resp = _make_assistant_response()

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Tell me about Apple.",
            assistant_response=resp,
            uow=uow,
        )

        # First call is user message
        first_call_msg = uow.messages.create.call_args_list[0].args[0]
        assert first_call_msg.content == "Tell me about Apple."
        assert first_call_msg.role == MessageRole.user
        assert first_call_msg.thread_id == _THREAD_ID

    async def test_assistant_message_content_matches_response(self) -> None:
        """The assistant message persisted contains the response content."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase
        from rag_chat.domain.enums import MessageRole

        uow = _make_uow()
        resp = _make_assistant_response(content="Apple had record-breaking earnings.")

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="How did Apple do?",
            assistant_response=resp,
            uow=uow,
        )

        # Second call is assistant message
        second_call_msg = uow.messages.create.call_args_list[1].args[0]
        assert second_call_msg.content == "Apple had record-breaking earnings."
        assert second_call_msg.role == MessageRole.assistant

    async def test_assistant_message_has_provider_and_model(self) -> None:
        """Provider and model fields are set on the assistant message."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response(provider="openrouter", model="mistral-7b")

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        asst_msg = uow.messages.create.call_args_list[1].args[0]
        assert asst_msg.provider == "openrouter"
        assert asst_msg.model == "mistral-7b"

    async def test_commits_unit_of_work(self) -> None:
        """UoW.commit() is called exactly once."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response()

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        uow.commit.assert_called_once()

    async def test_updates_thread_last_msg(self) -> None:
        """uow.threads.update_last_msg is called with thread_id and new entity IDs."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        entity_id = uuid4()
        # Build a minimal ResolvedEntity with only entity_id accessible
        entity = MagicMock()
        entity.entity_id = entity_id

        uow = _make_uow()
        resp = _make_assistant_response(resolved_entities=(entity,))

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        uow.threads.update_last_msg.assert_called_once()
        call_args = uow.threads.update_last_msg.call_args
        assert call_args.args[0] == _THREAD_ID
        assert entity_id in call_args.args[2]

    async def test_token_counts_propagated(self) -> None:
        """Token counts from the response are set on the assistant message."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response(token_count_in=200, token_count_out=75)

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        asst_msg = uow.messages.create.call_args_list[1].args[0]
        assert asst_msg.token_count_in == 200
        assert asst_msg.token_count_out == 75

    async def test_none_token_counts_allowed(self) -> None:
        """None token counts (provider didn't report them) are accepted."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()
        resp = _make_assistant_response(token_count_in=None, token_count_out=None)

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        asst_msg = uow.messages.create.call_args_list[1].args[0]
        assert asst_msg.token_count_in is None
        assert asst_msg.token_count_out is None


class TestChatPersistenceLazyThreadCreation:
    """Bug 3 Fix: FK violation when thread_id not yet in DB — lazy thread creation."""

    def _make_uow_thread_missing(self) -> MagicMock:
        """UoW where threads.get returns None (thread not yet in DB)."""
        uow = MagicMock()
        uow.messages = MagicMock()
        uow.messages.create = AsyncMock(return_value=None)
        uow.threads = MagicMock()
        uow.threads.get = AsyncMock(return_value=None)  # thread missing → None
        uow.threads.create = AsyncMock(return_value=None)
        uow.threads.update_last_msg = AsyncMock(return_value=None)
        uow.commit = AsyncMock(return_value=None)
        return uow

    def _make_uow_thread_exists(self) -> MagicMock:
        """UoW where threads.get returns a mock thread (thread already exists)."""
        uow = MagicMock()
        uow.messages = MagicMock()
        uow.messages.create = AsyncMock(return_value=None)
        uow.threads = MagicMock()
        uow.threads.get = AsyncMock(return_value=MagicMock())  # thread found
        uow.threads.create = AsyncMock(return_value=None)
        uow.threads.update_last_msg = AsyncMock(return_value=None)
        uow.commit = AsyncMock(return_value=None)
        return uow

    async def test_creates_thread_when_missing_and_tenant_user_known(self) -> None:
        """When thread_id has no DB row and tenant_id+user_id are provided,
        a new thread row is created before messages are inserted."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = self._make_uow_thread_missing()
        resp = _make_assistant_response()
        tenant_id = uuid4()
        user_id = uuid4()

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # get() must be called to check existence
        uow.threads.get.assert_called_once_with(_THREAD_ID, user_id, tenant_id)
        # create() must be called because get() returned None
        uow.threads.create.assert_called_once()
        # Messages still created normally
        assert uow.messages.create.call_count == 2

    async def test_does_not_create_thread_when_already_exists(self) -> None:
        """When the thread is found in the DB, no duplicate create() is issued."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = self._make_uow_thread_exists()
        resp = _make_assistant_response()
        tenant_id = uuid4()
        user_id = uuid4()

        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        uow.threads.create.assert_not_called()
        assert uow.messages.create.call_count == 2

    async def test_skips_thread_check_when_tenant_or_user_none(self) -> None:
        """When tenant_id or user_id are omitted (sync path default), no get/create is called."""
        from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase

        uow = _make_uow()  # basic mock — no threads.get
        resp = _make_assistant_response()

        # Calling without tenant_id/user_id (original signature compatibility)
        await ChatPersistenceUseCase().execute(
            thread_id=_THREAD_ID,
            user_message="Test",
            assistant_response=resp,
            uow=uow,
        )

        # threads.get should not be called when tenant_id/user_id are None
        uow.threads.update_last_msg.assert_called_once()
        assert uow.messages.create.call_count == 2


class TestThinkBlockFilter:
    """Bug 1 Fix: _ThinkBlockFilter strips <think> blocks from streaming tokens."""

    def _filter(self) -> object:
        from rag_chat.application.pipeline.chat_pipeline import _ThinkBlockFilter

        return _ThinkBlockFilter()

    def test_passthrough_no_think_block(self) -> None:
        """Plain text without think tags passes through unmodified.

        The filter buffers the last (max_tag_len - 1) chars in case an open tag
        is split at the chunk boundary, so we must flush() to get the remainder.
        """
        f = self._filter()
        out = f.feed("Hello world")
        result = out + f.flush()
        assert "Hello" in result
        assert "world" in result

    def test_strips_complete_think_block_in_single_chunk(self) -> None:
        """A single chunk with complete <think>...</think> emits only the text after."""
        f = self._filter()
        out = f.feed("<think>internal reasoning here</think>actual answer")
        remaining = f.flush()
        full = out + remaining
        assert "actual answer" in full
        assert "internal reasoning" not in full
        assert "<think>" not in full

    def test_strips_think_block_split_across_chunks(self) -> None:
        """<think>...</think> split at boundaries is handled correctly."""
        f = self._filter()
        out1 = f.feed("<thi")
        out2 = f.feed("nk>hidden</th")
        out3 = f.feed("ink>visible")
        result = out1 + out2 + out3 + f.flush()
        assert "visible" in result
        assert "hidden" not in result

    def test_strips_reasoning_tag(self) -> None:
        """<reasoning> variant is also stripped."""
        f = self._filter()
        out = f.feed("<reasoning>chain of thought</reasoning>clean answer")
        result = out + f.flush()
        assert "clean answer" in result
        assert "chain of thought" not in result

    def test_strips_scratchpad_tag(self) -> None:
        """<scratchpad> variant is also stripped."""
        f = self._filter()
        out = f.feed("<scratchpad>notes</scratchpad>response")
        result = out + f.flush()
        assert "response" in result
        assert "notes" not in result

    def test_flush_discards_incomplete_think_block(self) -> None:
        """If stream ends mid-think-block, flush() discards the buffer (not shown to user)."""
        f = self._filter()
        f.feed("<think>never closed")
        result = f.flush()
        assert result == ""

    def test_case_insensitive_matching(self) -> None:
        """Tag detection is case-insensitive (THINK, Think, etc.)."""
        f = self._filter()
        out = f.feed("<THINK>hidden</THINK>shown")
        result = out + f.flush()
        assert "shown" in result
        assert "hidden" not in result

    def test_empty_feed(self) -> None:
        """Empty chunk produces empty output without error."""
        f = self._filter()
        assert f.feed("") == ""
        assert f.flush() == ""
