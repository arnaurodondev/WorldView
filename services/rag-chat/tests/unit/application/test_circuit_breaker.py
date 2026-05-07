"""Unit tests for SourceCircuitBreaker (T-D-1-01) and CB wiring (B-6 regression).

PLAN-0084 A-2: tests for SETNX probe gating (T-A-2-02), TTL cleanup (T-A-2-03),
Prometheus gauge (T-A-2-04), cooldown/probe-TTL defaults.
"""

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
    set_nx_return: bool = True,
) -> AsyncMock:
    """Build a mock ValkeyClient.

    PLAN-0076 Wave B-2 (BP-403): record_failure() now uses ``execute_lua_script``
    which returns the failure count directly (no pipeline indexing needed). Pass
    ``lua_return`` to control the failure count seen by ``record_failure()``.
    PLAN-0084 A-2: ``set_nx_return`` controls whether the SETNX probe wins.
    """
    valkey = AsyncMock()
    valkey.get.return_value = get_return
    valkey.set = AsyncMock()
    valkey.set_nx = AsyncMock(return_value=set_nx_return)
    valkey.delete = AsyncMock()
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
    # Note: cool_down_seconds=120 is the new default (was 3600 before PLAN-0084 A-2)
    cb = SourceCircuitBreaker(valkey, "relations", failure_threshold=3, cool_down_seconds=120)

    await cb.record_failure()

    # Verify state was set to "open" with cool-down TTL
    valkey.set.assert_awaited_once_with("rag:cb:relations:state", "open", ttl=120)

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
    """record_success() clears state and probe keys (PLAN-0084 A-2 F-X05 fix).

    The failures ZSET is NOT deleted — it expires naturally via its TTL to avoid
    a race with concurrent failure writers (F-X05 Option A).
    """
    valkey = _make_valkey(get_return=None)
    cb = SourceCircuitBreaker(valkey, "claims")
    await cb.record_success()

    # State key and probe key deleted; failures ZSET NOT deleted
    deleted_keys = [call.args[0] for call in valkey.delete.call_args_list]
    assert "rag:cb:claims:state" in deleted_keys
    assert "rag:cb:claims:probe" in deleted_keys
    # The failures ZSET should NOT be in the deleted keys
    assert "rag:cb:claims:failures" not in deleted_keys


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
            # PLAN-0084 A-2: default lowered to 120; still valid to pass explicitly
            cool_down_seconds=120,
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


# ── PLAN-0084 A-2: SETNX probe gating + cooldown + gauge ─────────────────────


@pytest.mark.unit
async def test_is_open_returns_True_when_state_set() -> None:
    """state key present with value 'open' → is_open() returns True (F-X01)."""
    valkey = _make_valkey(get_return="open")
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test1", failure_threshold=3)
    assert await cb.is_open() is True


@pytest.mark.unit
async def test_is_open_admits_one_probe_after_cooldown() -> None:
    """When state key absent and SETNX wins → exactly one probe caller gets False."""
    # state absent → set_nx returns True (won probe slot)
    valkey = _make_valkey(get_return=None, set_nx_return=True)
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test2", probe_ttl_seconds=5)

    result = await cb.is_open()
    assert result is False

    # Verify SETNX was called with correct key and TTL
    valkey.set_nx.assert_awaited_once_with("rag:cb:chunk_a2_test2:probe", "1", ex=5)


@pytest.mark.unit
async def test_is_open_other_probes_return_True() -> None:
    """When state key absent but SETNX loses → caller returns True (backed off)."""
    # set_nx returns False → another caller already holds the probe slot
    valkey = _make_valkey(get_return=None, set_nx_return=False)
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test3", probe_ttl_seconds=5)

    result = await cb.is_open()
    assert result is True


@pytest.mark.unit
async def test_record_success_clears_probe_key() -> None:
    """record_success() deletes both state key and probe key (F-X05)."""
    valkey = _make_valkey()
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test4")
    await cb.record_success()

    deleted = [call.args[0] for call in valkey.delete.call_args_list]
    assert "rag:cb:chunk_a2_test4:probe" in deleted


@pytest.mark.unit
def test_default_cool_down_is_120s() -> None:
    """SourceCircuitBreaker default cool_down_seconds is 120 (PLAN-0084 A-2 F-X04)."""
    valkey = AsyncMock()
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test5")
    assert cb._cooldown == 120


@pytest.mark.unit
def test_probe_ttl_default_5s() -> None:
    """SourceCircuitBreaker default probe_ttl_seconds is 5 (PLAN-0084 A-2 F-X01)."""
    valkey = AsyncMock()
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test6")
    assert cb._probe_ttl == 5


@pytest.mark.unit
async def test_record_success_does_not_delete_failures_zset() -> None:
    """F-X05: record_success deletes state + probe but NOT the failures ZSET."""
    valkey = _make_valkey()
    cb = SourceCircuitBreaker(valkey, "chunk_a2_test7")
    await cb.record_success()

    deleted = [call.args[0] for call in valkey.delete.call_args_list]
    assert "rag:cb:chunk_a2_test7:failures" not in deleted


@pytest.mark.unit
async def test_gauge_set_to_1_on_open() -> None:
    """When breaker trips, rag_circuit_breaker_open gauge is set to 1 (T-A-2-04)."""
    from prometheus_client import REGISTRY

    def _gauge_value(source: str) -> float:
        for m in REGISTRY.collect():
            for s in m.samples:
                if s.name == "rag_circuit_breaker_open" and s.labels.get("source") == source:
                    return s.value
        return -1.0

    valkey = _make_valkey(lua_return=3)
    # Use unique source name to avoid cross-test gauge contamination (BP-404)
    source_name = "chunk_gauge_open_test"
    cb = SourceCircuitBreaker(valkey, source_name, failure_threshold=3, cool_down_seconds=120)

    await cb.record_failure()

    assert _gauge_value(source_name) == 1.0


@pytest.mark.unit
async def test_gauge_set_to_0_on_recovery() -> None:
    """After record_success(), rag_circuit_breaker_open gauge is set to 0 (T-A-2-04)."""
    from prometheus_client import REGISTRY

    def _gauge_value(source: str) -> float:
        for m in REGISTRY.collect():
            for s in m.samples:
                if s.name == "rag_circuit_breaker_open" and s.labels.get("source") == source:
                    return s.value
        return -1.0

    valkey = _make_valkey(lua_return=3)
    source_name = "chunk_gauge_recovery_test"
    cb = SourceCircuitBreaker(valkey, source_name, failure_threshold=3, cool_down_seconds=120)

    # First trip the breaker
    await cb.record_failure()
    assert _gauge_value(source_name) == 1.0

    # Now recover
    await cb.record_success()
    assert _gauge_value(source_name) == 0.0


@pytest.mark.unit
async def test_concurrent_failure_after_success_does_not_corrupt() -> None:
    """record_success() + concurrent record_failure() does not corrupt state.

    F-X05 Option A: failures ZSET is NOT deleted by record_success(), so a
    concurrent failure that ZADD'd before record_success() ran is still in
    the ZSET. The breaker will trip again if the count is >= threshold.
    """
    valkey = _make_valkey(lua_return=1)  # single failure, below threshold
    cb = SourceCircuitBreaker(valkey, "chunk_a2_concurrent_test", failure_threshold=3)

    # Simulate recovery then a new failure
    await cb.record_success()
    await cb.record_failure()

    # Below threshold — state key should NOT be set
    valkey.set.assert_not_awaited()
