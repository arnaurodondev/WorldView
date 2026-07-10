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

    async def test_post_commit_hook_failure_increments_prometheus_counter(self):
        """Hook failure must increment s3_post_commit_hook_failures_total (Option C observability)."""
        from market_data.infrastructure.metrics.prometheus import s3_post_commit_hook_failures_total

        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        before = s3_post_commit_hook_failures_total._value.get()

        async def _failing_hook() -> None:
            raise RuntimeError("valkey down")

        async with uow:
            uow.schedule_post_commit(_failing_hook())
            await uow.commit()

        after = s3_post_commit_hook_failures_total._value.get()
        assert after == before + 1, f"Expected counter to increment by 1 (before={before}, after={after})"

    async def test_post_commit_hook_success_does_not_increment_counter(self):
        """Counter must NOT increment when the hook succeeds."""
        from market_data.infrastructure.metrics.prometheus import s3_post_commit_hook_failures_total

        mock_session = AsyncMock()
        factory = _make_session_factory(mock_session)
        uow = SqlAlchemyUnitOfWork(write_factory=factory, read_factory=factory)

        before = s3_post_commit_hook_failures_total._value.get()

        async def _ok_hook() -> None:
            pass

        async with uow:
            uow.schedule_post_commit(_ok_hook())
            await uow.commit()

        after = s3_post_commit_hook_failures_total._value.get()
        assert after == before, "Counter must not change when hook succeeds"


class TestUoWLazyReadSession:
    """2026-06-16 session-optimization #1: the read session is created lazily.

    Write-only consumers (the OHLCV materializer) must NOT open a second Postgres
    connection just by entering the UoW — it doubled the per-UoW connection count
    and capped consumer replica scaling.  The read session is built on first
    ``_read()``/``get_read_session()`` use only.
    """

    async def test_read_session_not_created_on_enter(self):
        """Entering the UoW must NOT call the read factory (write-only path)."""
        write_session = AsyncMock()
        read_session = AsyncMock()
        write_factory = _make_session_factory(write_session)
        read_factory = _make_session_factory(read_session)
        uow = SqlAlchemyUnitOfWork(write_factory=write_factory, read_factory=read_factory)

        async with uow:
            # No read accessor touched → read factory never called.
            read_factory.assert_not_called()
            write_factory.assert_called_once()
        # Never created → never closed.
        read_session.close.assert_not_called()

    async def test_read_session_created_lazily_on_first_access(self):
        """First get_read_session() builds the read session once and reuses it."""
        write_session = AsyncMock()
        read_session = AsyncMock()
        write_factory = _make_session_factory(write_session)
        read_factory = _make_session_factory(read_session)
        uow = SqlAlchemyUnitOfWork(write_factory=write_factory, read_factory=read_factory)

        async with uow:
            s1 = uow.get_read_session()
            s2 = uow.get_read_session()
            assert s1 is read_session
            assert s2 is read_session  # reused, not rebuilt
            read_factory.assert_called_once()
        # Created → closed exactly once on exit.
        read_session.close.assert_called_once()

    async def test_read_accessor_raises_when_not_entered(self):
        """_read() outside the context manager must raise (write session absent)."""
        write_factory = _make_session_factory(AsyncMock())
        read_factory = _make_session_factory(AsyncMock())
        uow = SqlAlchemyUnitOfWork(write_factory=write_factory, read_factory=read_factory)

        with pytest.raises(RuntimeError, match="not entered"):
            uow.get_read_session()


class TestUoWPredictionStreamAccessors:
    """PLAN-0056 A2: the deeper prediction-stream repos are wired to the right
    session (write accessors → write session, ``*_read`` → read session) and the
    write-side accessors are cached (lazy-init, one instance per UoW)."""

    async def test_write_accessors_bind_write_session_and_cache(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
            PgPredictionMarketOIRepository,
            PgPredictionMarketPricesRepository,
            PgPredictionMarketTradesRepository,
        )

        write_session = AsyncMock()
        read_session = AsyncMock()
        write_factory = _make_session_factory(write_session)
        read_factory = _make_session_factory(read_session)
        uow = SqlAlchemyUnitOfWork(write_factory=write_factory, read_factory=read_factory)

        async with uow:
            prices = uow.prediction_market_prices
            trades = uow.prediction_market_trades
            oi = uow.prediction_market_oi
            events = uow.prediction_events

            assert isinstance(prices, PgPredictionMarketPricesRepository)
            assert isinstance(trades, PgPredictionMarketTradesRepository)
            assert isinstance(oi, PgPredictionMarketOIRepository)
            assert isinstance(events, PgPredictionMarketEventsRepository)

            # All bound to the WRITE session.
            assert prices._session is write_session
            assert trades._session is write_session
            assert oi._session is write_session
            assert events._session is write_session

            # Lazy-init cache: repeated access returns the same instance.
            assert uow.prediction_market_prices is prices
            assert uow.prediction_market_trades is trades
            assert uow.prediction_market_oi is oi
            assert uow.prediction_events is events

            # Write-only path so far → read factory untouched.
            read_factory.assert_not_called()

    async def test_read_accessors_bind_read_session(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
            PgPredictionMarketOIRepository,
            PgPredictionMarketPricesRepository,
            PgPredictionMarketTradesRepository,
        )

        write_session = AsyncMock()
        read_session = AsyncMock()
        write_factory = _make_session_factory(write_session)
        read_factory = _make_session_factory(read_session)
        uow = SqlAlchemyUnitOfWork(write_factory=write_factory, read_factory=read_factory)

        async with uow:
            assert isinstance(uow.prediction_market_prices_read, PgPredictionMarketPricesRepository)
            assert isinstance(uow.prediction_market_trades_read, PgPredictionMarketTradesRepository)
            assert isinstance(uow.prediction_market_oi_read, PgPredictionMarketOIRepository)
            assert isinstance(uow.prediction_events_read, PgPredictionMarketEventsRepository)
            # All bound to the READ (replica) session.
            assert uow.prediction_market_prices_read._session is read_session
            assert uow.prediction_market_trades_read._session is read_session
            assert uow.prediction_market_oi_read._session is read_session
            assert uow.prediction_events_read._session is read_session


class TestReadOnlyUoWPredictionStreamAccessors:
    """The read-only UoW (R27) exposes the same ``*_read`` accessors, bound to
    its single read session."""

    async def test_readonly_accessors_bind_read_session(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
            PgPredictionMarketOIRepository,
            PgPredictionMarketPricesRepository,
            PgPredictionMarketTradesRepository,
        )
        from market_data.infrastructure.db.uow import SqlAlchemyReadOnlyUnitOfWork

        read_session = AsyncMock()
        read_factory = _make_session_factory(read_session)
        uow = SqlAlchemyReadOnlyUnitOfWork(read_factory=read_factory)

        async with uow:
            assert isinstance(uow.prediction_market_prices_read, PgPredictionMarketPricesRepository)
            assert isinstance(uow.prediction_market_trades_read, PgPredictionMarketTradesRepository)
            assert isinstance(uow.prediction_market_oi_read, PgPredictionMarketOIRepository)
            assert isinstance(uow.prediction_events_read, PgPredictionMarketEventsRepository)
            assert uow.prediction_market_prices_read._session is read_session
            assert uow.prediction_events_read._session is read_session
