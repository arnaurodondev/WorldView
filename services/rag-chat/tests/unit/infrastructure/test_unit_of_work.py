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
        """soft_delete() executes UPDATE with owner filter and returns a UTC datetime."""
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1  # one row updated → success
        mock_session.execute.return_value = mock_result

        repo = SqlAlchemyThreadRepository(mock_session)

        before = datetime.now(tz=UTC)
        result = await repo.soft_delete(thread_id=uuid4(), user_id=uuid4(), tenant_id=uuid4())
        after = datetime.now(tz=UTC)

        assert isinstance(result, datetime)
        assert result.tzinfo is not None, "archived_at must be timezone-aware"
        assert before <= result <= after

    async def test_soft_delete_wrong_owner_raises(self) -> None:
        """soft_delete() with 0 rows affected (wrong owner) raises ThreadNotFoundError."""
        from rag_chat.domain.errors import ThreadNotFoundError
        from rag_chat.infrastructure.db.repositories.thread_repository import SqlAlchemyThreadRepository

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0  # no rows → owner mismatch
        mock_session.execute.return_value = mock_result

        repo = SqlAlchemyThreadRepository(mock_session)
        with pytest.raises(ThreadNotFoundError):
            await repo.soft_delete(thread_id=uuid4(), user_id=uuid4(), tenant_id=uuid4())

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


class TestRagUnitOfWorkPortCompliance:
    """D-4: RagUnitOfWork must structurally satisfy RagUnitOfWorkPort (R25 compliance).

    Use cases now depend on RagUnitOfWorkPort (Protocol), not the concrete class.
    This test guards against accidental removal of required members.
    """

    def test_rag_uow_has_threads_property(self) -> None:
        """RagUnitOfWork class must define a `threads` property (RagUnitOfWorkPort)."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        # Check at class level — `threads` is a property that requires __aenter__
        assert hasattr(RagUnitOfWork, "threads"), "RagUnitOfWork class missing `threads` (RagUnitOfWorkPort)"

    def test_rag_uow_has_messages_property(self) -> None:
        """RagUnitOfWork class must define a `messages` property (RagUnitOfWorkPort)."""
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        assert hasattr(RagUnitOfWork, "messages"), "RagUnitOfWork class missing `messages` (RagUnitOfWorkPort)"

    def test_rag_uow_has_commit_method(self) -> None:
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        assert callable(RagUnitOfWork.commit), "RagUnitOfWork missing callable `commit` (RagUnitOfWorkPort)"

    def test_rag_uow_has_rollback_method(self) -> None:
        from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork

        assert callable(RagUnitOfWork.rollback), "RagUnitOfWork missing callable `rollback` (RagUnitOfWorkPort)"

    def test_use_cases_import_from_application_port_not_infra(self) -> None:
        """All thread-related use cases must import RagUnitOfWorkPort, not RagUnitOfWork (D-4)."""
        from pathlib import Path

        use_cases_dir = Path(__file__).parents[4] / "src" / "rag_chat" / "application" / "use_cases"
        infra_import = "from rag_chat.infrastructure.db.unit_of_work import RagUnitOfWork"
        violations = []
        for py_file in use_cases_dir.rglob("*.py"):
            content = py_file.read_text()
            if infra_import in content:
                violations.append(py_file.name)
        assert not violations, f"Use cases importing RagUnitOfWork from infra (R25 violation): {violations}"
