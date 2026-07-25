"""Unit tests for messaging.pg.advisory_lock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from messaging.pg.advisory_lock import (
    advisory_lock_id,
    pg_advisory_lock,
    pg_advisory_lock_pinned,
    pg_advisory_xact_lock,
)

pytestmark = pytest.mark.unit


class TestAdvisoryLockId:
    def test_deterministic_same_name(self) -> None:
        """Same name always produces the same lock ID."""
        assert advisory_lock_id("test") == advisory_lock_id("test")

    def test_deterministic_across_calls(self) -> None:
        """Multiple calls with the same input produce identical results."""
        ids = [advisory_lock_id("s4:fetch:eodhd") for _ in range(100)]
        assert len(set(ids)) == 1

    def test_different_names_different_ids(self) -> None:
        """Different names produce different IDs."""
        assert advisory_lock_id("source_a") != advisory_lock_id("source_b")

    def test_32bit_positive_range(self) -> None:
        """Result fits in a 32-bit positive integer."""
        for name in ["a", "b", "test", "s4:fetch:eodhd", "very-long-name" * 100]:
            lock_id = advisory_lock_id(name)
            assert 0 <= lock_id <= 0x7FFF_FFFF

    def test_uses_sha256_not_python_hash(self) -> None:
        """Verify the function produces the expected SHA-256 based result.

        Python's hash() is randomized per process (PYTHONHASHSEED), so if this
        test passes across runs it proves we're NOT using hash().
        """
        import hashlib

        name = "s4:fetch:eodhd"
        expected = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "big") & 0x7FFF_FFFF
        assert advisory_lock_id(name) == expected


class TestPgAdvisoryLock:
    @pytest.fixture()
    def mock_session(self) -> AsyncMock:
        session = AsyncMock()
        return session

    async def test_acquired_yields_true(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_lock(mock_session, "test") as acquired:
            assert acquired is True

    async def test_not_acquired_yields_false(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = False
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_lock(mock_session, "test") as acquired:
            assert acquired is False

    async def test_releases_on_exit(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_lock(mock_session, "test"):
            pass

        # Should have been called twice: acquire + release
        assert mock_session.execute.await_count == 2

    async def test_no_release_when_not_acquired(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = False
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_lock(mock_session, "test"):
            pass

        # Only called once: acquire attempt (no release)
        assert mock_session.execute.await_count == 1

    async def test_releases_on_exception(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="boom"):
            async with pg_advisory_lock(mock_session, "test"):
                raise ValueError("boom")

        # acquire + release even though body raised
        assert mock_session.execute.await_count == 2


class TestPgAdvisoryXactLock:
    """Transaction-scoped variant — MUST NOT issue an explicit unlock statement.

    Regression coverage for BP-752: pg_advisory_xact_lock relies entirely on
    Postgres auto-releasing the lock at commit/rollback of the CURRENT
    transaction, so unlike ``pg_advisory_lock`` there is no second ``execute``
    call on context-manager exit — asserting exactly ONE call (not two) is
    the whole point of this test class.
    """

    @pytest.fixture()
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    async def test_acquired_yields_true(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_xact_lock(mock_session, "test") as acquired:
            assert acquired is True

    async def test_not_acquired_yields_false(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = False
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_xact_lock(mock_session, "test") as acquired:
            assert acquired is False

    async def test_no_explicit_unlock_statement_on_exit(self, mock_session: AsyncMock) -> None:
        """Only the acquire statement is ever issued — no unlock call exists."""
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_xact_lock(mock_session, "test"):
            pass

        assert mock_session.execute.await_count == 1
        (sql_arg,), _ = mock_session.execute.await_args_list[0]
        assert "pg_try_advisory_xact_lock" in str(sql_arg)

    async def test_no_explicit_unlock_on_exception(self, mock_session: AsyncMock) -> None:
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="boom"):
            async with pg_advisory_xact_lock(mock_session, "test"):
                raise ValueError("boom")

        # Still only the acquire call — release happens via the transaction
        # rollback the caller performs on the exception path, not this helper.
        assert mock_session.execute.await_count == 1

    async def test_session_never_committed_by_the_helper(self, mock_session: AsyncMock) -> None:
        """The helper must never commit/rollback the session itself.

        Releasing the lock is entirely the caller's responsibility (via the
        session's own commit/rollback lifecycle) — this helper only ever
        issues the acquire SELECT.
        """
        result = MagicMock()
        result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=result)

        async with pg_advisory_xact_lock(mock_session, "test"):
            pass

        mock_session.commit.assert_not_awaited()
        mock_session.rollback.assert_not_awaited()


class TestPgAdvisoryLockPinned:
    """Dedicated-connection variant — must never return the connection mid-lock."""

    @pytest.fixture()
    def mock_engine(self) -> MagicMock:
        engine = MagicMock()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = True
        conn.execute = AsyncMock(return_value=result)
        engine.connect = AsyncMock(return_value=conn)
        engine._conn = conn  # stash for assertions
        return engine

    async def test_acquired_yields_true(self, mock_engine: MagicMock) -> None:
        async with pg_advisory_lock_pinned(mock_engine, "test") as acquired:
            assert acquired is True

    async def test_not_acquired_yields_false(self, mock_engine: MagicMock) -> None:
        mock_engine._conn.execute.return_value.scalar.return_value = False
        async with pg_advisory_lock_pinned(mock_engine, "test") as acquired:
            assert acquired is False

    async def test_connection_not_closed_until_after_unlock(self, mock_engine: MagicMock) -> None:
        """The SAME connection object must issue both acquire and unlock."""
        conn = mock_engine._conn
        async with pg_advisory_lock_pinned(mock_engine, "test"):
            # Only the acquire statement + its commit have run so far.
            assert conn.execute.await_count == 1
            conn.close.assert_not_awaited()

        # After exit: unlock statement issued on the SAME connection, then closed.
        assert conn.execute.await_count == 2
        conn.close.assert_awaited_once()
        # engine.connect() must only be called ONCE for the whole lifetime —
        # proves no re-checkout happened between acquire and release.
        mock_engine.connect.assert_awaited_once()

    async def test_no_unlock_or_close_skip_when_not_acquired(self, mock_engine: MagicMock) -> None:
        mock_engine._conn.execute.return_value.scalar.return_value = False
        conn = mock_engine._conn

        async with pg_advisory_lock_pinned(mock_engine, "test"):
            pass

        # Only the (failed) acquire attempt — no unlock statement.
        assert conn.execute.await_count == 1
        conn.close.assert_awaited_once()

    async def test_connection_closed_on_exception(self, mock_engine: MagicMock) -> None:
        conn = mock_engine._conn
        with pytest.raises(ValueError, match="boom"):
            async with pg_advisory_lock_pinned(mock_engine, "test"):
                raise ValueError("boom")

        # Unlock still runs (acquired=True) and the connection is still closed.
        assert conn.execute.await_count == 2
        conn.close.assert_awaited_once()
