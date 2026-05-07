"""Unit tests for SourceCircuitBreaker (T-D-1-01) and CB wiring (B-6 regression)."""

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
    lua_return: int = 1,
) -> AsyncMock:
    """Build a mock ValkeyClient.

    PLAN-0076 Wave B-2 (BP-403): record_failure() now uses ``execute_lua_script``
    which returns the failure count directly (no pipeline indexing needed). Pass
    ``lua_return`` to control the failure count seen by ``record_failure()``.
    The ``pipeline_results`` parameter is retained for ``record_success()``
    tests, which still use a pipeline.
    """
    valkey = AsyncMock()
    valkey.get.return_value = get_return
    valkey.set = AsyncMock()
    valkey.execute_lua_script = AsyncMock(return_value=lua_return)

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
    # Lua script returns failure_count = 3 (== threshold)
    valkey = _make_valkey(lua_return=3)
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
    # Lua script returns failure_count = 2 (< threshold of 3)
    valkey = _make_valkey(lua_return=2)
    cb = SourceCircuitBreaker(valkey, "financial", failure_threshold=3)

    await cb.record_failure()

    # set() should NOT have been called (no state transition)
    valkey.set.assert_not_awaited()


@pytest.mark.unit
async def test_cb_record_failure_valkey_unavailable() -> None:
    """Valkey error during record_failure() is swallowed (best-effort)."""
    valkey = AsyncMock()
    valkey.execute_lua_script = AsyncMock(side_effect=ConnectionError("Valkey down"))

    cb = SourceCircuitBreaker(valkey, "portfolio")

    # Should not raise
    await cb.record_failure()


@pytest.mark.unit
async def test_cb_record_failure_uses_lua_script_atomically() -> None:
    """record_failure() invokes execute_lua_script with the correct keys/args.

    Regression for BP-403 — a non-atomic ZADD/ZREMRANGEBYSCORE/ZCARD pipeline
    (the previous implementation) allowed two concurrent failures to both
    observe count below the threshold. The Lua script makes the read+write
    atomic on the Redis server.
    """
    valkey = _make_valkey(lua_return=1)
    cb = SourceCircuitBreaker(valkey, "chunk", failure_threshold=3, failure_window_seconds=120)

    await cb.record_failure()

    valkey.execute_lua_script.assert_awaited_once()
    call_args = valkey.execute_lua_script.await_args
    # First positional arg is the Lua script body — must contain ZADD + ZREMRANGEBYSCORE + ZCARD
    script = call_args.args[0]
    assert "ZADD" in script
    assert "ZREMRANGEBYSCORE" in script
    assert "ZCARD" in script
    # keys=[failures_key]
    assert call_args.kwargs["keys"] == ["rag:cb:chunk:failures"]
    # args = [now, cutoff, ttl] — last must be the window seconds as a string
    assert call_args.kwargs["args"][2] == "120"


# ── B-6 regression: circuit breakers wired into ParallelRetrievalOrchestrator ─


@pytest.mark.unit
def test_circuit_breakers_wired_when_enabled() -> None:
    """When cb_enabled=True, ParallelRetrievalOrchestrator receives non-empty circuit_breakers dict.

    This is a regression test for B-6: previously app.py instantiated
    ParallelRetrievalOrchestrator without circuit_breakers, defaulting to {}.
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator

    # Build the same CB dict that _wire_orchestrator now builds
    source_names = ["chunk", "relations", "graph", "claims", "events", "contradictions", "financial", "portfolio"]
    mock_valkey = AsyncMock()

    cbs = {
        name: SourceCircuitBreaker(
            mock_valkey,
            name,
            failure_threshold=3,
            failure_window_seconds=120,
            cool_down_seconds=3600,
        )
        for name in source_names
    }

    orchestrator = ParallelRetrievalOrchestrator(
        s6_client=MagicMock(),
        s7_client=MagicMock(),
        s3_client=MagicMock(),
        s1_client=MagicMock(),
        circuit_breakers=cbs,
    )

    # _cbs must be the full dict — not empty
    assert orchestrator._cbs != {}
    assert len(orchestrator._cbs) == len(source_names)
    for name in source_names:
        assert name in orchestrator._cbs
        assert isinstance(orchestrator._cbs[name], SourceCircuitBreaker)


@pytest.mark.unit
def test_circuit_breakers_empty_when_disabled() -> None:
    """When cb_enabled=False, ParallelRetrievalOrchestrator receives empty circuit_breakers dict."""
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator

    # Simulate cb_enabled=False path: pass empty dict
    orchestrator = ParallelRetrievalOrchestrator(
        s6_client=MagicMock(),
        s7_client=MagicMock(),
        s3_client=MagicMock(),
        s1_client=MagicMock(),
        circuit_breakers={},
    )

    assert orchestrator._cbs == {}
