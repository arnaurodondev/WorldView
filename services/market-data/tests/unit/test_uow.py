"""Unit tests for SqlAlchemyUnitOfWork (MD-017).

These tests use mock session factories — no live database required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.events import InstrumentCreated
from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.unit


def _make_session_factory(session: AsyncMock) -> MagicMock:
    """Return a mock session factory that produces the given mock session."""
    factory = MagicMock()
    factory.return_value = session
    return factory


class TestUoWCommit:
    async def test_uow_commit_commits_session(self):
        """commit() must call session.commit()."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        async with uow:
            await uow.commit()

        mock_session.commit.assert_called_once()


class TestUoWRollback:
    async def test_uow_rollback_on_exception(self):
        """On exception inside the context, rollback() must be called."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("simulated error")

        mock_session.rollback.assert_called_once()


class TestUoWCollectEvents:
    async def test_uow_collects_events(self):
        """collect_event() must accumulate events in collected_events."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        event = InstrumentCreated(
            instrument_id="inst-1",
            security_id="sec-1",
            symbol="AAPL",
            exchange="NASDAQ",
        )
        async with uow:
            uow.collect_event(event)
            assert len(uow.collected_events) == 1
            assert uow.collected_events[0] is event

    async def test_collected_events_cleared_after_commit(self):
        """collected_events must be empty after commit()."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        event = InstrumentCreated(instrument_id="inst-1", security_id="sec-1", symbol="AAPL", exchange="NASDAQ")
        async with uow:
            uow.collect_event(event)
            await uow.commit()
            assert uow.collected_events == []


class TestUoWOutboxNotifier:
    async def test_uow_notifies_outbox_on_commit(self):
        """commit() must call outbox_notifier with collected events."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        notifier = AsyncMock()

        uow = SqlAlchemyUnitOfWork(
            write_factory=factory,
            read_factory=factory,
            outbox_notifier=notifier,
        )

        event = InstrumentCreated(instrument_id="inst-1", security_id="sec-1", symbol="AAPL", exchange="NASDAQ")
        async with uow:
            uow.collect_event(event)
            await uow.commit()

        notifier.assert_called_once_with([event])

    async def test_uow_no_notifier_no_error(self):
        """commit() without a notifier and with events must not raise."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        event = InstrumentCreated(instrument_id="inst-1", security_id="sec-1", symbol="AAPL", exchange="NASDAQ")
        async with uow:
            uow.collect_event(event)
            await uow.commit()  # no notifier — should be silent


# ---------------------------------------------------------------------------
# F-DS-006: Session always closed even when rollback raises
# ---------------------------------------------------------------------------


class TestUoWSessionCleanup:
    async def test_uow_session_closed_when_rollback_raises(self):
        """Sessions must be closed even if rollback() raises (F-DS-006)."""
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock(side_effect=OSError("connection lost"))
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("trigger rollback path")

        # Sessions must be closed regardless of rollback failure
        mock_session.close.assert_called()


# ---------------------------------------------------------------------------
# F-DS-015: Post-commit hook errors do not propagate
# ---------------------------------------------------------------------------


class TestUoWPostCommitHooks:
    async def test_post_commit_hook_runs_after_successful_commit(self):
        """Scheduled hook is called after DB commit succeeds."""
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        hook_called = False

        async def _hook() -> None:
            nonlocal hook_called
            hook_called = True

        async with uow:
            uow.schedule_post_commit(_hook())
            await uow.commit()

        assert hook_called

    async def test_post_commit_hook_failure_does_not_propagate(self):
        """Hook exception must be swallowed and logged, not raised (F-DS-015).

        A cache-invalidation failure must not dead-letter the Kafka message —
        the DB commit has already succeeded and is durable.
        """
        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        async def _failing_hook() -> None:
            raise RuntimeError("cache unavailable")

        async with uow:
            uow.schedule_post_commit(_failing_hook())
            # Must not raise despite hook failure
            await uow.commit()

        # Session.commit() must still have been called
        mock_session.commit.assert_called_once()
