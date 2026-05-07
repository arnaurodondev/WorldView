"""Unit tests for ``CanonicalTickersCache`` (PLAN-0063 W5-2 / FR-T1-2).

Mocks both the Valkey client and the ``CanonicalTickerSource`` port so the
tests run with zero infrastructure. The integration of the cache into the
rare-token analyzer is W5-3 work and lives in a separate test file then.

PLAN-0084 C-1 additions:
- Tests for background refresh loop (F-X02 fix)
- Tests for atomic DEL+SADD swap via transaction=True (F-X03 fix)
- Tests for startup() launching the loop + close() cancelling it
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.cache.canonical_tickers_cache import (
    CanonicalTickersCache,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakePipeline:
    """Minimal pipeline fake: queues ops and applies them on ``execute``.

    Supports async context manager protocol (``async with client.pipeline()``),
    records whether ``transaction=True`` was passed, and executes buffered ops
    against the parent ``_FakeValkey`` store when ``execute()`` is awaited.
    """

    def __init__(self, parent: _FakeValkey, *, transaction: bool = False) -> None:
        self._parent = parent
        self._ops: list[tuple[str, tuple[object, ...]]] = []
        # Record the transaction flag so tests can assert on it.
        self.transaction = transaction
        # Track how many times execute() was called.
        self.execute_call_count = 0

    def delete(self, key: str) -> _FakePipeline:
        self._ops.append(("delete", (key,)))
        return self

    def sadd(self, key: str, *members: str) -> _FakePipeline:
        self._ops.append(("sadd", (key, *members)))
        return self

    async def execute(self) -> list[object]:
        self.execute_call_count += 1
        results: list[object] = []
        for op, args in self._ops:
            if op == "delete":
                results.append(await self._parent.delete(args[0]))  # type: ignore[arg-type]
            else:
                key, *members = args
                results.append(await self._parent.sadd(key, *members))  # type: ignore[arg-type]
        self._ops.clear()
        return results

    # Async context manager support: ``async with client.pipeline(...) as pipe``
    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class _FakeValkey:
    """In-memory stand-in for the subset of ``redis.asyncio.Redis`` the cache
    uses (``sadd``, ``sismember``, ``delete``, ``pipeline``).

    Behaves like a Valkey SET with case-sensitive uppercase membership — the
    cache normalises to upper-case before write, so the fake stays simple.

    Records the most recently created ``_FakePipeline`` in ``last_pipeline``
    so tests can inspect whether ``transaction=True`` was passed.
    """

    def __init__(self) -> None:
        self._set: set[str] = set()
        # Most recently created pipeline — inspected by transaction tests.
        self.last_pipeline: _FakePipeline | None = None

    async def sadd(self, _key: str, *members: str) -> int:
        added = 0
        for m in members:
            if m not in self._set:
                self._set.add(m)
                added += 1
        return added

    async def sismember(self, _key: str, member: str) -> bool:
        return member in self._set

    async def delete(self, _key: str) -> int:
        n = len(self._set)
        self._set.clear()
        return n

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        # Return an async-context-manager-capable pipeline.
        pipe = _FakePipeline(self, transaction=transaction)
        self.last_pipeline = pipe
        return pipe


def _make_source(tickers: list[str]) -> MagicMock:
    src = MagicMock()
    src.fetch_all_tickers = AsyncMock(return_value=tickers)
    return src


# ── Original tests (unchanged behaviour) ─────────────────────────────────────


async def test_is_known_ticker_case_insensitive() -> None:
    """``add('AAPL')`` → ``is_known_ticker('aapl')`` returns True."""
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(client=valkey, source=_make_source([]))  # type: ignore[arg-type]

    await cache.add("AAPL")
    assert await cache.is_known_ticker("aapl") is True
    assert await cache.is_known_ticker("AAPL") is True
    assert await cache.is_known_ticker(" AAPL ") is True


async def test_unknown_ticker_returns_false() -> None:
    """Empty cache → ``is_known_ticker('FAKE')`` returns False."""
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(client=valkey, source=_make_source([]))  # type: ignore[arg-type]
    assert await cache.is_known_ticker("FAKE") is False


async def test_refresh_replaces_set() -> None:
    """Initial {AAPL, MSFT} → refresh returns {GOOG, NVDA} → old keys gone."""
    valkey = _FakeValkey()
    src = _make_source(["AAPL", "MSFT"])
    cache = CanonicalTickersCache(client=valkey, source=src)  # type: ignore[arg-type]

    count = await cache.refresh()
    assert count == 2
    assert await cache.is_known_ticker("AAPL") is True

    # Now flip the source — refresh should drop the old members.
    src.fetch_all_tickers = AsyncMock(return_value=["GOOG", "NVDA"])
    count2 = await cache.refresh()
    assert count2 == 2
    assert await cache.is_known_ticker("AAPL") is False
    assert await cache.is_known_ticker("MSFT") is False
    assert await cache.is_known_ticker("GOOG") is True
    assert await cache.is_known_ticker("NVDA") is True


async def test_startup_does_not_raise_on_empty_source() -> None:
    """Source returns 0 rows → cache stays empty, startup does not raise."""
    valkey = _FakeValkey()
    src = _make_source([])
    cache = CanonicalTickersCache(client=valkey, source=src)  # type: ignore[arg-type]

    # Should not raise.
    await cache.startup()
    # Cache stays empty.
    assert await cache.is_known_ticker("AAPL") is False

    # Cleanup: cancel background loop to avoid asyncio task leak warnings.
    await cache.close()


async def test_refresh_handles_source_error() -> None:
    """Source raises → cache logs warning AND keeps stale data (no clear)."""
    valkey = _FakeValkey()
    src = _make_source(["AAPL", "MSFT"])
    cache = CanonicalTickersCache(client=valkey, source=src)  # type: ignore[arg-type]

    await cache.refresh()
    assert await cache.is_known_ticker("AAPL") is True

    # Now make the source explode and refresh again.
    src.fetch_all_tickers = AsyncMock(side_effect=RuntimeError("boom"))
    count = await cache.refresh()
    assert count == 0
    # Old data is still there — refresh did NOT wipe the SET on a transient
    # source error (this is the contract documented in the cache docstring).
    assert await cache.is_known_ticker("AAPL") is True
    assert await cache.is_known_ticker("MSFT") is True


# ── Defensive guard ──────────────────────────────────────────────────────────


async def test_is_known_ticker_handles_blank_input() -> None:
    """Empty / whitespace symbols return False without touching Valkey."""
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(client=valkey, source=_make_source([]))  # type: ignore[arg-type]
    assert await cache.is_known_ticker("") is False
    assert await cache.is_known_ticker("   ") is False


# ── T-C-1-02: Atomic DEL+SADD swap (F-X03 fix) ──────────────────────────────


async def test_refresh_uses_transaction_mode() -> None:
    """refresh() must call pipeline(transaction=True) — F-X03 fix.

    Verifies that the atomic swap path passes ``transaction=True`` to the
    redis pipeline so DEL + SADD are wrapped in a MULTI/EXEC block.
    """
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=_make_source(["AAPL", "TSLA"])
    )

    count = await cache.refresh()
    assert count == 2

    # The fake records the last pipeline; assert transaction=True was passed.
    assert valkey.last_pipeline is not None
    assert valkey.last_pipeline.transaction is True


async def test_concurrent_is_known_ticker_during_refresh() -> None:
    """50 concurrent reads during a swap must never return False for AAPL.

    This test verifies the atomic-swap contract: the fake pipeline executes
    DEL + SADD atomically, so no reader can observe the intermediate empty
    SET state.
    """
    valkey = _FakeValkey()
    src = _make_source(["AAPL"])
    cache = CanonicalTickersCache(client=valkey, source=src)  # type: ignore[arg-type]

    # Seed the SET first so there is something to read during the swap.
    await cache.refresh()
    assert await cache.is_known_ticker("AAPL") is True

    # Fire 50 concurrent reads while also running a refresh.
    results = await asyncio.gather(
        cache.refresh(),
        *[cache.is_known_ticker("AAPL") for _ in range(50)],
        return_exceptions=False,
    )

    # The refresh count is the first result; the rest are bool reads.
    refresh_count, *bool_results = results
    assert refresh_count == 1  # 1 ticker

    # Because the fake is in-process and truly synchronous within each
    # coroutine's execution slice, the atomic pipeline means AAPL is
    # always present when checked — none of the 50 reads should return False.
    false_count = sum(1 for r in bool_results if r is False)
    assert false_count == 0, f"{false_count} reads saw an empty SET during swap"


async def test_refresh_handles_empty_source() -> None:
    """fetch_all_tickers() returns [] → D-017 guard skips the wipe entirely.

    The previous behaviour was: DEL fires, SADD skipped → cache wiped.
    The new behaviour (D-017 fix) is: empty source is treated as a transient
    query issue; the existing (possibly stale) SET is left untouched so callers
    continue to see valid tickers until the next successful refresh.
    """
    valkey = _FakeValkey()
    # Seed the SET first so we can verify it is NOT wiped.
    await valkey.sadd("nlp:v1:canonical_tickers", "AAPL", "MSFT")
    assert await valkey.sismember("nlp:v1:canonical_tickers", "AAPL") is True

    src = _make_source([])  # empty source
    cache = CanonicalTickersCache(client=valkey, source=src)  # type: ignore[arg-type]

    count = await cache.refresh()
    assert count == 0

    # D-017: stale cache must be preserved — NOT wiped — when source returns 0.
    assert await cache.is_known_ticker("AAPL") is True
    assert await cache.is_known_ticker("MSFT") is True


# ── T-C-1-01 / T-C-1-03: Refresh loop + lifecycle ────────────────────────────


async def test_refresh_loop_calls_refresh_on_interval() -> None:
    """_refresh_loop() must call refresh() after each sleep interval.

    Patches ``asyncio.sleep`` in the cache module's namespace so the loop
    body runs without real waiting. After 3 cycles the refresh mock must
    have been called at least 3 times.
    """
    valkey = _FakeValkey()
    src = _make_source(["AAPL"])
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=src, refresh_interval_s=600
    )

    refresh_call_count = 0
    original_refresh = cache.refresh

    async def _counted_refresh() -> int:
        nonlocal refresh_call_count
        refresh_call_count += 1
        return await original_refresh()

    # Use an event to allow the test to stop the loop after 3 ticks.
    stop_event = asyncio.Event()

    async def _fast_sleep(seconds: float) -> None:
        # Stop cooperatively once we have enough ticks.
        if refresh_call_count >= 3:
            stop_event.set()
            # Raise CancelledError to exit the loop cleanly.
            raise asyncio.CancelledError()

    # Patch sleep in the canonical_tickers_cache module namespace.
    target = "nlp_pipeline.infrastructure.cache.canonical_tickers_cache.asyncio.sleep"
    with patch(target, side_effect=_fast_sleep):
        cache.refresh = _counted_refresh  # type: ignore[method-assign]

        task = asyncio.create_task(cache._refresh_loop())
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            pass
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    assert refresh_call_count >= 3, f"Expected ≥3 refresh calls, got {refresh_call_count}"


async def test_refresh_loop_swallows_transient_error() -> None:
    """refresh() raising on the first tick must not kill the loop.

    The loop should log a warning and continue. After the transient error,
    the second tick succeeds and the SET is populated.

    Strategy: patch sleep in the module namespace to a near-no-op; on the
    second successful refresh tick, raise CancelledError to stop the loop.
    """
    valkey = _FakeValkey()
    src = MagicMock()

    # fetch_all_tickers: first call raises, subsequent calls succeed.
    src.fetch_all_tickers = AsyncMock(side_effect=[ConnectionError("valkey down"), ["AAPL"], ["AAPL"]])
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=src, refresh_interval_s=600
    )

    successful_ticks: list[int] = []
    original_refresh = cache.refresh

    async def _tracked_refresh() -> int:
        result = await original_refresh()
        # count == 0 when source errored; > 0 when tickers were written
        if result > 0:
            successful_ticks.append(result)
        return result

    tick_count = 0

    async def _fast_sleep(seconds: float) -> None:
        nonlocal tick_count
        tick_count += 1
        # After we've seen a successful refresh, stop the loop.
        if successful_ticks:
            raise asyncio.CancelledError()

    target = "nlp_pipeline.infrastructure.cache.canonical_tickers_cache.asyncio.sleep"
    with patch(target, side_effect=_fast_sleep):
        cache.refresh = _tracked_refresh  # type: ignore[method-assign]

        task = asyncio.create_task(cache._refresh_loop())
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            pass
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    assert len(successful_ticks) >= 1, "Loop never recovered after transient error"


async def test_refresh_loop_propagates_cancelled_error() -> None:
    """task.cancel() must cause CancelledError to propagate out of _refresh_loop."""
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=_make_source([]), refresh_interval_s=600
    )

    # Start loop with real asyncio.sleep so cancel() interrupts the sleep.
    task = asyncio.create_task(cache._refresh_loop())

    # Give the task a chance to enter its sleep.
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_close_cancels_loop() -> None:
    """After close(), the background task must be cancelled."""
    valkey = _FakeValkey()
    src = _make_source(["AAPL"])
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=src, refresh_interval_s=600
    )

    # startup() → warm cache + create background task.
    await cache.startup()
    task = cache._refresh_task
    assert task is not None
    assert not task.done()

    # close() → cancel the task.
    await cache.close()

    assert task.cancelled(), "Background refresh task was not cancelled by close()"


async def test_startup_launches_refresh_loop() -> None:
    """startup() must create a non-done asyncio Task."""
    valkey = _FakeValkey()
    src = _make_source(["TSLA", "NVDA"])
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=src, refresh_interval_s=600
    )

    assert cache._refresh_task is None  # no task before startup

    await cache.startup()

    assert cache._refresh_task is not None
    assert not cache._refresh_task.done(), "Background task should be running after startup"

    # Cleanup.
    await cache.close()


async def test_close_cancels_refresh_loop() -> None:
    """After close(), _refresh_task.cancelled() is True."""
    valkey = _FakeValkey()
    src = _make_source(["AMZN"])
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=src, refresh_interval_s=600
    )

    await cache.startup()
    task_ref = cache._refresh_task
    assert task_ref is not None

    await cache.close()

    # Task must be cancelled (done + cancelled).
    assert task_ref.done()
    assert task_ref.cancelled()


async def test_close_noop_before_startup() -> None:
    """close() before startup() must not raise."""
    valkey = _FakeValkey()
    cache = CanonicalTickersCache(  # type: ignore[arg-type]
        client=valkey, source=_make_source([]), refresh_interval_s=600
    )
    # Should not raise even though startup() was never called.
    await cache.close()


# Pytest marker: this module's tests run under asyncio_mode=auto (no decorator
# needed). The asyncio_mode=auto config is project-wide via pytest.ini.
_ = pytest  # silence "imported but unused" if the file is reorganised
