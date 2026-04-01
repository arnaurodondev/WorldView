"""Unit tests for messaging.pg.advisory_lock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from messaging.pg.advisory_lock import advisory_lock_id, pg_advisory_lock

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
