"""Unit tests for thread use cases (T-D-4-01).

Tests: CreateThread, ListThreads, GetThread, DeleteThread.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
_THREAD_ID = UUID("00000000-0000-0000-0000-000000000003")


def _make_mock_uow() -> MagicMock:
    """Return a mock UoW with async-compatible repository stubs."""
    uow = MagicMock()
    uow.threads = MagicMock()
    uow.threads.create = AsyncMock(return_value=None)
    uow.threads.get = AsyncMock(return_value=None)
    uow.threads.list_active = AsyncMock(return_value=([], 0))
    uow.threads.soft_delete = AsyncMock(return_value=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC))
    uow.commit = AsyncMock(return_value=None)
    return uow


def _make_thread(archived: bool = False) -> object:
    from rag_chat.domain.entities.conversation import ConversationThread

    now = datetime.now(tz=UTC)
    return ConversationThread(
        thread_id=_THREAD_ID,
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        created_at=now,
        updated_at=now,
        title="Test thread",
        entity_ids=(),
        messages=(),
        archived_at=now if archived else None,
    )


# ── CreateThreadUseCase ───────────────────────────────────────────────────────


class TestCreateThreadUseCase:
    async def test_create_thread_uses_uuidv7(self) -> None:
        """thread_id assigned by new_uuid7() → version == 7."""
        from rag_chat.application.use_cases.create_thread import CreateThreadUseCase

        uow = _make_mock_uow()
        uc = CreateThreadUseCase()
        thread = await uc.execute(uow, user_id=_USER_ID, tenant_id=_TENANT_ID, title=None, entity_ids=[])

        assert thread.thread_id.version == 7

    async def test_create_thread_persists_and_commits(self) -> None:
        """create() and commit() are both called exactly once."""
        from rag_chat.application.use_cases.create_thread import CreateThreadUseCase

        uow = _make_mock_uow()
        uc = CreateThreadUseCase()
        await uc.execute(uow, user_id=_USER_ID, tenant_id=_TENANT_ID, title="My thread", entity_ids=[])

        uow.threads.create.assert_awaited_once()
        uow.commit.assert_awaited_once()

    async def test_create_thread_stores_entity_ids(self) -> None:
        """entity_ids from the request are stored as a tuple on the thread."""
        from rag_chat.application.use_cases.create_thread import CreateThreadUseCase

        entity_id = uuid4()
        uow = _make_mock_uow()
        uc = CreateThreadUseCase()
        thread = await uc.execute(
            uow,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            title=None,
            entity_ids=[entity_id],
        )

        assert thread.entity_ids == (entity_id,)


# ── ListThreadsUseCase ────────────────────────────────────────────────────────


class TestListThreadsUseCase:
    async def test_list_threads_delegates_to_list_active(self) -> None:
        """Use case calls list_active (archived threads excluded at repo level)."""
        from rag_chat.application.use_cases.list_threads import ListThreadsUseCase

        thread = _make_thread()
        uow = _make_mock_uow()
        uow.threads.list_active = AsyncMock(return_value=([thread], 1))

        uc = ListThreadsUseCase()
        threads, total = await uc.execute(uow, user_id=_USER_ID, tenant_id=_TENANT_ID)

        uow.threads.list_active.assert_awaited_once_with(_USER_ID, _TENANT_ID, limit=20, offset=0)
        assert total == 1
        assert threads[0] is thread

    async def test_list_threads_clamps_limit_to_100(self) -> None:
        """limit > 100 is clamped to 100 before calling the repository."""
        from rag_chat.application.use_cases.list_threads import ListThreadsUseCase

        uow = _make_mock_uow()
        uc = ListThreadsUseCase()
        await uc.execute(uow, user_id=_USER_ID, tenant_id=_TENANT_ID, limit=999)

        _, kwargs = uow.threads.list_active.call_args
        assert kwargs["limit"] == 100


# ── GetThreadUseCase ──────────────────────────────────────────────────────────


class TestGetThreadUseCase:
    async def test_get_thread_returns_thread(self) -> None:
        """Repository returns a thread → use case returns it unchanged."""
        from rag_chat.application.use_cases.get_thread import GetThreadUseCase

        thread = _make_thread()
        uow = _make_mock_uow()
        uow.threads.get = AsyncMock(return_value=thread)

        uc = GetThreadUseCase()
        result = await uc.execute(uow, thread_id=_THREAD_ID, user_id=_USER_ID)

        assert result is thread

    async def test_get_thread_wrong_owner_raises(self) -> None:
        """Repository returns None (wrong user_id) → ThreadNotFoundError raised."""
        from rag_chat.application.use_cases.get_thread import GetThreadUseCase
        from rag_chat.domain.errors import ThreadNotFoundError

        uow = _make_mock_uow()
        uow.threads.get = AsyncMock(return_value=None)  # ownership check failed

        uc = GetThreadUseCase()
        with pytest.raises(ThreadNotFoundError):
            await uc.execute(uow, thread_id=_THREAD_ID, user_id=uuid4())


# ── DeleteThreadUseCase ───────────────────────────────────────────────────────


class TestDeleteThreadUseCase:
    async def test_delete_thread_sets_archived_at(self) -> None:
        """soft_delete is called with thread_id, user_id, tenant_id; returned archived_at equals repo's value."""
        from rag_chat.application.use_cases.delete_thread import DeleteThreadUseCase

        expected_archived_at = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
        uow = _make_mock_uow()
        uow.threads.soft_delete = AsyncMock(return_value=expected_archived_at)

        uc = DeleteThreadUseCase()
        archived_at = await uc.execute(uow, thread_id=_THREAD_ID, user_id=_USER_ID, tenant_id=_TENANT_ID)

        uow.threads.soft_delete.assert_awaited_once_with(_THREAD_ID, _USER_ID, _TENANT_ID)
        uow.commit.assert_awaited_once()
        assert archived_at == expected_archived_at

    async def test_delete_thread_not_found_raises(self) -> None:
        """Repo raises ThreadNotFoundError when thread not found / wrong owner."""
        from rag_chat.application.use_cases.delete_thread import DeleteThreadUseCase
        from rag_chat.domain.errors import ThreadNotFoundError

        uow = _make_mock_uow()
        uow.threads.soft_delete = AsyncMock(side_effect=ThreadNotFoundError("not found"))

        uc = DeleteThreadUseCase()
        with pytest.raises(ThreadNotFoundError):
            await uc.execute(uow, thread_id=_THREAD_ID, user_id=_USER_ID, tenant_id=_TENANT_ID)

        uow.commit.assert_not_awaited()
