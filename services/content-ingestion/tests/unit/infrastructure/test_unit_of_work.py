"""Unit tests for SqlaUnitOfWork (T-B-2-04)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _mock_factory(session: AsyncMock | None = None) -> MagicMock:
    """Create a mock async_sessionmaker that returns the given session."""
    s = session or AsyncMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = s
    return factory


class TestSqlaUnitOfWork:
    async def test_uow_commit(self) -> None:
        """commit() calls session.commit and runs callbacks."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        factory = MagicMock()
        factory.return_value = session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

        callback = MagicMock(return_value=None)

        async with SqlaUnitOfWork(factory) as uow:
            uow.on_commit(callback)
            await uow.commit()

        session.commit.assert_called_once()
        callback.assert_called_once()

    async def test_uow_rollback_on_exception(self) -> None:
        """Exception in context triggers rollback."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        factory = MagicMock()
        factory.return_value = session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

        with pytest.raises(ValueError, match="test error"):
            async with SqlaUnitOfWork(factory) as _uow:
                raise ValueError("test error")

        session.rollback.assert_called_once()

    async def test_uow_exposes_repositories(self) -> None:
        """All 5 repos accessible as properties after entering context."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.commit = AsyncMock()

        factory = MagicMock()
        factory.return_value = session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

        async with SqlaUnitOfWork(factory) as uow:
            assert uow.tasks is not None
            assert uow.sources is not None
            assert uow.fetch_logs is not None
            assert uow.outbox is not None
            assert uow.adapter_state is not None

    async def test_uow_read_fallback(self) -> None:
        """When read_factory is None, sources repo uses write session."""
        write_session = AsyncMock()
        write_session.__aenter__ = AsyncMock(return_value=write_session)
        write_session.__aexit__ = AsyncMock(return_value=None)
        write_session.commit = AsyncMock()

        factory = MagicMock()
        factory.return_value = write_session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

        async with SqlaUnitOfWork(factory, read_factory=None) as uow:
            # Sources uses read session, which should fallback to write
            assert uow.sources._session is write_session

    async def test_uow_dual_sessions(self) -> None:
        """When read_factory differs, sources uses read session."""
        write_session = AsyncMock(name="write")
        write_session.__aenter__ = AsyncMock(return_value=write_session)
        write_session.__aexit__ = AsyncMock(return_value=None)
        write_session.commit = AsyncMock()

        read_session = AsyncMock(name="read")
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=None)

        write_factory = MagicMock(name="write_factory")
        write_factory.return_value = write_session

        read_factory = MagicMock(name="read_factory")
        read_factory.return_value = read_session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

        async with SqlaUnitOfWork(write_factory, read_factory=read_factory) as uow:
            # Tasks should use write session
            assert uow.tasks._session is write_session
            # Sources uses write session (admin use cases need write access)
            assert uow.sources._session is write_session


class TestSqlaReadOnlyUnitOfWork:
    async def test_read_uow_uses_read_session(self) -> None:
        """ReadOnlyUnitOfWork uses the read factory session for all repos."""
        read_session = AsyncMock(name="read")
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=None)

        read_factory = MagicMock(name="read_factory")
        read_factory.return_value = read_session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork

        async with SqlaReadOnlyUnitOfWork(read_factory) as uow:
            assert uow.sources._session is read_session
            assert uow.tasks._session is read_session
            assert uow.adapter_state._session is read_session
            assert uow.dlq._session is read_session

    async def test_read_uow_has_no_commit(self) -> None:
        """ReadOnlyUnitOfWork has no commit method (enforced by type system)."""
        from content_ingestion.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork

        assert not hasattr(SqlaReadOnlyUnitOfWork, "commit")

    async def test_read_uow_closes_session(self) -> None:
        """Exiting the context closes the read session."""
        read_session = AsyncMock(name="read")
        read_session.__aenter__ = AsyncMock(return_value=read_session)
        read_session.__aexit__ = AsyncMock(return_value=None)

        read_factory = MagicMock(name="read_factory")
        read_factory.return_value = read_session

        from content_ingestion.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork

        async with SqlaReadOnlyUnitOfWork(read_factory):
            pass

        read_session.__aexit__.assert_called_once()
