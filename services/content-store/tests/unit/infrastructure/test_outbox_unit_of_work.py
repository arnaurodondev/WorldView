"""Unit tests for SqlAlchemyUnitOfWork (F-QA-005).

Validates the R26 invariant: __aexit__ MUST NOT auto-commit; only explicit
commit() calls commit the session.  Also covers rollback, outbox property
guard, and graceful cleanup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_uow() -> tuple[object, MagicMock, AsyncMock]:
    """Return (uow, session_factory_mock, session_mock)."""
    from content_store.infrastructure.messaging.outbox.unit_of_work import SqlAlchemyUnitOfWork

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=mock_session)
    uow = SqlAlchemyUnitOfWork(session_factory)
    return uow, session_factory, mock_session


class TestSqlAlchemyUnitOfWorkR26:
    """R26: __aexit__ MUST NOT commit — only explicit commit() commits."""

    async def test_aexit_without_exception_does_not_commit(self) -> None:
        """Happy-path __aexit__ must NOT call session.commit (R26)."""
        uow, _, mock_session = _make_uow()

        async with uow:  # type: ignore[attr-defined]
            pass  # no exception

        mock_session.commit.assert_not_called()

    async def test_explicit_commit_calls_session_commit(self) -> None:
        """commit() must delegate to session.commit()."""
        uow, _, mock_session = _make_uow()

        async with uow:  # type: ignore[attr-defined]
            await uow.commit()  # type: ignore[attr-defined]

        mock_session.commit.assert_called_once()

    async def test_aexit_on_exception_calls_rollback_not_commit(self) -> None:
        """On exception, __aexit__ must rollback and NOT commit."""
        uow, _, mock_session = _make_uow()

        with pytest.raises(ValueError):
            async with uow:  # type: ignore[attr-defined]
                raise ValueError("boom")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    async def test_explicit_rollback_calls_session_rollback(self) -> None:
        """rollback() must delegate to session.rollback()."""
        uow, _, mock_session = _make_uow()

        async with uow:  # type: ignore[attr-defined]
            await uow.rollback()  # type: ignore[attr-defined]

        mock_session.rollback.assert_called()


class TestSqlAlchemyUnitOfWorkOutboxProperty:
    async def test_outbox_raises_if_not_entered(self) -> None:
        """Accessing .outbox before __aenter__ must raise RuntimeError."""
        from content_store.infrastructure.messaging.outbox.unit_of_work import SqlAlchemyUnitOfWork

        uow = SqlAlchemyUnitOfWork(MagicMock())

        with pytest.raises(RuntimeError, match="not entered"):
            _ = uow.outbox

    async def test_outbox_accessible_after_enter(self) -> None:
        """After __aenter__, .outbox must return an OutboxRepository."""
        from content_store.infrastructure.db.repositories.outbox import OutboxRepository

        uow, _, _ = _make_uow()

        async with uow:  # type: ignore[attr-defined]
            assert isinstance(uow.outbox, OutboxRepository)  # type: ignore[attr-defined]
