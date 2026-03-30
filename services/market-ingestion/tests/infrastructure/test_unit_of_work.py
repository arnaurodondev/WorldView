"""Unit tests for SqlaUnitOfWork — R26 Option B compliance.

Verifies that __aexit__ never auto-commits (R26 / STANDARDS.md §17).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session() -> AsyncMock:
    """A fully mocked AsyncSession."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_factory(mock_session: AsyncMock) -> MagicMock:
    """A session factory that always returns the same mock session."""
    factory = MagicMock(return_value=mock_session)
    return factory


@pytest.mark.asyncio
async def test_sqla_uow_aexit_does_not_auto_commit(mock_session: AsyncMock, mock_factory: MagicMock) -> None:
    """R26 / Option B: clean __aexit__ must NOT call session.commit()."""
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    uow = SqlaUnitOfWork(mock_factory)
    async with uow:
        pass  # clean exit — no exception, no explicit commit

    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_sqla_uow_aexit_rollbacks_on_exception(mock_session: AsyncMock, mock_factory: MagicMock) -> None:
    """On exception, __aexit__ must call rollback (not commit)."""
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    uow = SqlaUnitOfWork(mock_factory)
    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("test error")

    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_sqla_uow_session_closed_after_clean_exit(mock_session: AsyncMock, mock_factory: MagicMock) -> None:
    """Session is closed via __aexit__ even on a clean exit (no exception)."""
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    uow = SqlaUnitOfWork(mock_factory)
    async with uow:
        pass

    # Session __aexit__ is called by _close_sessions()
    mock_session.__aexit__.assert_called()


@pytest.mark.asyncio
async def test_sqla_uow_explicit_commit_works(mock_session: AsyncMock, mock_factory: MagicMock) -> None:
    """Explicit await uow.commit() commits the session exactly once."""
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    uow = SqlaUnitOfWork(mock_factory)
    async with uow:
        await uow.commit()

    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_sqla_uow_session_closed_when_rollback_raises(mock_session: AsyncMock, mock_factory: MagicMock) -> None:
    """Session is closed in finally even when rollback raises (BP-037)."""
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    mock_session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))

    uow = SqlaUnitOfWork(mock_factory)
    # The original ValueError must propagate; rollback failure is swallowed
    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("original error")

    # Session must still be closed despite rollback failure
    mock_session.__aexit__.assert_called()
