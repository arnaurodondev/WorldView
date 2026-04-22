"""Unit tests for SourceCircuitBreaker (T-D-1-01)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.application.pipeline.circuit_breaker import SourceCircuitBreaker

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valkey(
    *,
    get_return: str | None = None,
    pipeline_results: list | None = None,
) -> AsyncMock:
    """Build a mock ValkeyClient with configurable pipeline results."""
    valkey = AsyncMock()
    valkey.get.return_value = get_return
    valkey.set = AsyncMock()

    pipe = AsyncMock()
    pipe.zadd = MagicMock()
    pipe.zremrangebyscore = MagicMock()
    pipe.zcard = MagicMock()
    pipe.expire = MagicMock()
    pipe.delete = MagicMock()
    pipe.execute.return_value = pipeline_results or [1, 0, 1, True]

    @asynccontextmanager
    async def _pipeline(*, transaction: bool = False):
        yield pipe

    valkey.pipeline = _pipeline
    return valkey


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_cb_closed_initially() -> None:
    """New circuit breaker with no state key -> CLOSED (is_open=False)."""
    valkey = _make_valkey(get_return=None)
    cb = SourceCircuitBreaker(valkey, "chunk", failure_threshold=3)

    result = await cb.is_open()

    assert result is False
    valkey.get.assert_awaited_once_with("rag:cb:chunk:state")


@pytest.mark.unit
async def test_cb_opens_after_threshold() -> None:
    """After N failures within the window, is_open() returns True."""
    # Pipeline returns failure_count = 3 (== threshold)
    valkey = _make_valkey(pipeline_results=[1, 0, 3, True])
    cb = SourceCircuitBreaker(valkey, "relations", failure_threshold=3, cool_down_seconds=3600)

    await cb.record_failure()

    # Verify state was set to "open" with cool-down TTL
    valkey.set.assert_awaited_once_with("rag:cb:relations:state", "open", ttl=3600)

    # Now is_open should return True when state key reads "open"
    valkey.get.return_value = "open"
    assert await cb.is_open() is True


@pytest.mark.unit
async def test_cb_half_open_after_cooldown() -> None:
    """After cool_down, state key expires (None) -> is_open() returns False."""
    # Simulate post-cool-down: Valkey TTL expired, key is gone
    valkey = _make_valkey(get_return=None)
    cb = SourceCircuitBreaker(valkey, "graph")

    # Key absent means CLOSED/HALF_OPEN -> probe allowed
    assert await cb.is_open() is False


@pytest.mark.unit
async def test_cb_closes_on_success() -> None:
    """record_success() clears state and failures (HALF_OPEN -> CLOSED)."""
    valkey = _make_valkey(get_return=None)
    pipe_mock = AsyncMock()
    pipe_mock.delete = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[1, 1])

    @asynccontextmanager
    async def _pipeline(*, transaction: bool = False):
        yield pipe_mock

    valkey.pipeline = _pipeline

    cb = SourceCircuitBreaker(valkey, "claims")
    await cb.record_success()

    # Both state and failures keys should be deleted
    assert pipe_mock.delete.call_count == 2
    pipe_mock.execute.assert_awaited_once()


@pytest.mark.unit
async def test_cb_valkey_unavailable_fail_open() -> None:
    """Valkey error -> is_open() returns False (fail-open, never block)."""
    valkey = AsyncMock()
    valkey.get.side_effect = ConnectionError("Valkey down")

    cb = SourceCircuitBreaker(valkey, "events")
    result = await cb.is_open()

    assert result is False


@pytest.mark.unit
async def test_cb_below_threshold_does_not_trip() -> None:
    """Fewer failures than threshold -> state key is NOT set."""
    # Pipeline returns failure_count = 2 (< threshold of 3)
    valkey = _make_valkey(pipeline_results=[1, 0, 2, True])
    cb = SourceCircuitBreaker(valkey, "financial", failure_threshold=3)

    await cb.record_failure()

    # set() should NOT have been called (no state transition)
    valkey.set.assert_not_awaited()


@pytest.mark.unit
async def test_cb_record_failure_valkey_unavailable() -> None:
    """Valkey error during record_failure() is swallowed (best-effort)."""
    valkey = AsyncMock()

    @asynccontextmanager
    async def _pipeline(*, transaction: bool = False):
        raise ConnectionError("Valkey down")
        yield  # pragma: no cover

    valkey.pipeline = _pipeline

    cb = SourceCircuitBreaker(valkey, "portfolio")

    # Should not raise
    await cb.record_failure()
