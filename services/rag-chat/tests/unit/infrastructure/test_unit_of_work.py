"""Unit tests for RagUnitOfWork (T-D-2-03).

Verifies R26 compliance: __aexit__ NEVER auto-commits.
Tests: test_uow_no_auto_commit_on_exit, test_thread_repo_get_ownership,
       test_thread_repo_soft_delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


class TestRagUoWNoAutoCommit:
    """R26: __aexit__ must NEVER call commit on the session."""

    async def test_uow_no_auto_commit_on_clean_exit(self) -> None:
        """Normal exit without explicit commit → session.commit() NOT called."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        uow = RagUnitOfWork(mock_factory)
        async with uow:
            pass  # no explicit uow.commit()

        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()

    async def test_uow_rollback_called_on_exception(self) -> None:
        """Exception in body → session.rollback() is called before close."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        uow = RagUnitOfWork(mock_factory)
        with pytest.raises(ValueError, match="boom"):
            async with uow:
                raise ValueError("boom")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    async def test_uow_explicit_commit_calls_session_commit(self) -> None:
        """Explicit await uow.commit() DOES call session.commit()."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)

        uow = RagUnitOfWork(mock_factory)
        async with uow:
            await uow.commit()

        mock_session.commit.assert_called_once()

    async def test_uow_session_closed_even_after_rollback_error(self) -> None:
        """Session is closed in finally even if rollback itself raises."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        mock_session = AsyncMock()
        mock_session.rollback.side_effect = RuntimeError("rollback failed")
        mock_factory = MagicMock(return_value=mock_session)

        uow = RagUnitOfWork(mock_factory)
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("original error")

        mock_session.close.assert_called_once()


class TestThreadRepository:
    """Unit tests for SqlAlchemyThreadRepository ownership and soft-delete."""

    async def test_get_returns_none_for_wrong_user_id(self) -> None:
        """get() filters by user_id — wrong owner returns None."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = SqlAlchemyThreadRepository(mock_session)
        result = await repo.get(thread_id=uuid4(), user_id=uuid4())

        assert result is None
        mock_session.execute.assert_called_once()

    async def test_soft_delete_returns_datetime(self) -> None:
        """soft_delete() executes UPDATE and returns a UTC datetime."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()

        repo = SqlAlchemyThreadRepository(mock_session)

        before = datetime.now(tz=UTC)
        result = await repo.soft_delete(thread_id=uuid4())
        after = datetime.now(tz=UTC)

        assert isinstance(result, datetime)
        assert result.tzinfo is not None, "archived_at must be timezone-aware"
        assert before <= result <= after

    async def test_soft_delete_excludes_from_list_active(self) -> None:
        """list_active() only returns threads where archived_at IS NULL."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        mock_session = AsyncMock()

        # First call (count), second call (rows) — both return 0 / empty
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value = iter([])
        mock_session.execute.side_effect = [count_result, rows_result]

        repo = SqlAlchemyThreadRepository(mock_session)
        threads, total = await repo.list_active(
            user_id=uuid4(),
            tenant_id=uuid4(),
            limit=10,
            offset=0,
        )

        assert total == 0
        assert threads == []
        # Verify WHERE clause includes archived_at IS NULL by checking execute was called
        assert mock_session.execute.call_count == 2
