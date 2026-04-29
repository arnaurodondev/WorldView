"""Unit tests for thread use cases (T-D-4-01).

Tests: CreateThread, ListThreads, GetThread, DeleteThread.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
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

    async def test_create_thread_increments_thread_count_gauge(self) -> None:
        """rag_thread_count Gauge is incremented with the tenant_id label after commit."""
        from rag_chat.application.use_cases.create_thread import CreateThreadUseCase

        uow = _make_mock_uow()
        uc = CreateThreadUseCase()
        mock_gauge = MagicMock()
        with patch("rag_chat.application.use_cases.create_thread.rag_thread_count", mock_gauge):
            await uc.execute(uow, user_id=_USER_ID, tenant_id=_TENANT_ID, title=None, entity_ids=[])

        mock_gauge.labels.assert_called_once_with(tenant_id=str(_TENANT_ID))
        mock_gauge.labels.return_value.inc.assert_called_once()


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

    async def test_delete_thread_decrements_thread_count_gauge(self) -> None:
        """rag_thread_count Gauge is decremented with the tenant_id label after commit."""
        from rag_chat.application.use_cases.delete_thread import DeleteThreadUseCase

        uow = _make_mock_uow()
        uc = DeleteThreadUseCase()
        mock_gauge = MagicMock()
        with patch("rag_chat.application.use_cases.delete_thread.rag_thread_count", mock_gauge):
            await uc.execute(uow, thread_id=_THREAD_ID, user_id=_USER_ID, tenant_id=_TENANT_ID)

        mock_gauge.labels.assert_called_once_with(tenant_id=str(_TENANT_ID))
        mock_gauge.labels.return_value.dec.assert_called_once()


# ── UpdateThreadUseCase ───────────────────────────────────────────────────────


class TestUpdateThreadUseCase:
    """QA-iter1 MAJ-3: PATCH /threads/{id} with empty body must NOT clear title.

    The earlier draft passed ``title=None`` straight through to
    ``threads.update_title`` which wrote NULL into the persisted column.
    The use case now short-circuits the no-op path.
    """

    async def test_empty_patch_body_preserves_title_no_update(self) -> None:
        """When ``title is None`` (e.g. PATCH {}), the existing thread is returned unchanged."""
        from rag_chat.application.use_cases.update_thread import UpdateThreadUseCase

        existing = _make_thread()
        uow = _make_mock_uow()
        # ``threads.get`` returns the existing thread on the no-op path.
        uow.threads.get = AsyncMock(return_value=existing)
        # ``update_title`` MUST NOT be called when title is None.
        uow.threads.update_title = AsyncMock()

        uc = UpdateThreadUseCase()
        result = await uc.execute(
            uow,
            thread_id=_THREAD_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            title=None,
        )

        # Negative assertion: no UPDATE happened.
        uow.threads.update_title.assert_not_awaited()
        # commit also skipped — no write means nothing to flush.
        uow.commit.assert_not_awaited()
        # Returns the unchanged entity for the API to round-trip.
        assert result is existing

    async def test_empty_patch_body_unknown_thread_raises(self) -> None:
        """Even on the no-op path, a thread the user doesn't own must 404."""
        from rag_chat.application.use_cases.update_thread import UpdateThreadUseCase
        from rag_chat.domain.errors import ThreadNotFoundError

        uow = _make_mock_uow()
        uow.threads.get = AsyncMock(return_value=None)  # ownership filter rejected
        uow.threads.update_title = AsyncMock()

        uc = UpdateThreadUseCase()
        with pytest.raises(ThreadNotFoundError):
            await uc.execute(
                uow,
                thread_id=_THREAD_ID,
                user_id=_USER_ID,
                tenant_id=_TENANT_ID,
                title=None,
            )

        uow.threads.update_title.assert_not_awaited()
        uow.commit.assert_not_awaited()

    async def test_non_empty_title_does_update_and_commits(self) -> None:
        """When title is provided, the use case calls update_title + commits."""
        from rag_chat.application.use_cases.update_thread import UpdateThreadUseCase

        renamed = _make_thread()
        uow = _make_mock_uow()
        uow.threads.update_title = AsyncMock(return_value=renamed)

        uc = UpdateThreadUseCase()
        result = await uc.execute(
            uow,
            thread_id=_THREAD_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            title="New Title",
        )

        uow.threads.update_title.assert_awaited_once()
        uow.commit.assert_awaited_once()
        assert result is renamed
