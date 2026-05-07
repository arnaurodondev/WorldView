"""Unit tests for ``CanonicalTickersCache`` (PLAN-0063 W5-2 / FR-T1-2).

Mocks both the Valkey client and the ``CanonicalTickerSource`` port so the
tests run with zero infrastructure. The integration of the cache into the
rare-token analyzer is W5-3 work and lives in a separate test file then.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.cache.canonical_tickers_cache import (
    CanonicalTickersCache,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeValkey:
    """In-memory stand-in for the subset of ``redis.asyncio.Redis`` the cache
    uses (``sadd``, ``sismember``, ``delete``, ``pipeline``).

    Behaves like a Valkey SET with case-sensitive uppercase membership — the
    cache normalises to upper-case before write, so the fake stays simple.
    """

    def __init__(self) -> None:
        self._set: set[str] = set()

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

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    """Minimal pipeline fake: queues ops and applies them on ``execute``."""

    def __init__(self, parent: _FakeValkey) -> None:
        self._parent = parent
        self._ops: list[tuple[str, tuple[object, ...]]] = []

    def delete(self, key: str) -> _FakePipeline:
        self._ops.append(("delete", (key,)))
        return self

    def sadd(self, key: str, *members: str) -> _FakePipeline:
        self._ops.append(("sadd", (key, *members)))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for op, args in self._ops:
            if op == "delete":
                results.append(await self._parent.delete(args[0]))  # type: ignore[arg-type]
            else:
                key, *members = args
                results.append(await self._parent.sadd(key, *members))  # type: ignore[arg-type]
        self._ops.clear()
        return results


def _make_source(tickers: list[str]) -> MagicMock:
    src = MagicMock()
    src.fetch_all_tickers = AsyncMock(return_value=tickers)
    return src


# ── Tests ─────────────────────────────────────────────────────────────────────


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


# Pytest marker: this module's tests run under asyncio_mode=auto (no decorator
# needed). The asyncio_mode=auto config is project-wide via pytest.ini.
_ = pytest  # silence "imported but unused" if the file is reorganised
