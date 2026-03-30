"""Unit tests for WatchlistCache — cache-aside pattern with Valkey."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from alert.infrastructure.cache.watchlist_cache import WatchlistCache
from alert.infrastructure.clients.s1_client import S1Client, WatcherInfo


def _mock_valkey() -> AsyncMock:
    """Return a mock Valkey client."""
    return AsyncMock()


def _mock_s1(watchers: list[WatcherInfo] | None = None, *, failure: bool = False) -> AsyncMock:
    """Return a mock S1Client.

    Args:
        watchers: Watchers to return on success (default: empty list).
        failure:  When True the client signals an S1 error (ok=False).
    """
    mock = AsyncMock(spec=S1Client)
    if failure:
        mock.get_watchers_by_entity = AsyncMock(return_value=([], False))
    else:
        mock.get_watchers_by_entity = AsyncMock(return_value=(watchers or [], True))
    return mock


_COUNTER_PATH = "alert.infrastructure.cache.watchlist_cache.s10_s1_lookup_failed_total"


class TestWatchlistCache:
    @pytest.mark.unit
    async def test_cache_miss_calls_s1(self) -> None:
        """On cache miss, falls through to S1 and caches the result."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)  # miss
        watchers = [WatcherInfo("u1", "w1", ["SIGNAL"])]
        s1 = _mock_s1(watchers)

        cache = WatchlistCache(valkey, s1, ttl=300)
        result = await cache.get_watchers("entity-1")

        assert len(result) == 1
        assert result[0].user_id == "u1"
        s1.get_watchers_by_entity.assert_called_once_with("entity-1")
        valkey.set.assert_called_once()

    @pytest.mark.unit
    async def test_cache_hit_skips_s1(self) -> None:
        """On cache hit, returns cached data without calling S1."""
        cached_data = json.dumps([{"user_id": "u2", "watchlist_id": "w2", "alert_types": ["GRAPH_CHANGE"]}])
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=cached_data.encode())
        s1 = _mock_s1()

        cache = WatchlistCache(valkey, s1, ttl=300)
        result = await cache.get_watchers("entity-1")

        assert len(result) == 1
        assert result[0].user_id == "u2"
        s1.get_watchers_by_entity.assert_not_called()

    @pytest.mark.unit
    async def test_cache_miss_empty_s1_not_cached(self) -> None:
        """If S1 returns empty, don't cache the empty result."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)
        s1 = _mock_s1([])  # empty

        cache = WatchlistCache(valkey, s1, ttl=300)
        result = await cache.get_watchers("entity-1")

        assert result == []
        valkey.set.assert_not_called()

    @pytest.mark.unit
    async def test_invalidate_deletes_key(self) -> None:
        valkey = _mock_valkey()
        s1 = _mock_s1()

        cache = WatchlistCache(valkey, s1)
        await cache.invalidate("entity-1")

        valkey.delete.assert_called_once_with("s10:v1:watchlist:by_entity:entity-1")

    @pytest.mark.unit
    async def test_valkey_get_error_degrades_to_s1(self) -> None:
        """Valkey read failure → fall through to S1 (never raises)."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(side_effect=ConnectionError("redis down"))
        watchers = [WatcherInfo("u1", "w1")]
        s1 = _mock_s1(watchers)

        cache = WatchlistCache(valkey, s1, ttl=300)
        result = await cache.get_watchers("entity-1")

        assert len(result) == 1
        s1.get_watchers_by_entity.assert_called_once()

    @pytest.mark.unit
    async def test_valkey_set_error_silent(self) -> None:
        """Valkey write failure is silently logged, not raised."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock(side_effect=ConnectionError("redis down"))
        watchers = [WatcherInfo("u1", "w1")]
        s1 = _mock_s1(watchers)

        cache = WatchlistCache(valkey, s1, ttl=300)
        result = await cache.get_watchers("entity-1")

        # Should still return the S1 result even if caching fails
        assert len(result) == 1

    @pytest.mark.unit
    async def test_invalidate_error_silent(self) -> None:
        """Valkey delete failure is silently logged, not raised."""
        valkey = _mock_valkey()
        valkey.delete = AsyncMock(side_effect=ConnectionError("redis down"))
        s1 = _mock_s1()

        cache = WatchlistCache(valkey, s1)
        # Should not raise
        await cache.invalidate("entity-1")


# ── S1 failure signalling (T-A-2-02) ─────────────────────────────────────────


class TestS1FailureSignalling:
    @pytest.mark.unit
    async def test_s1_failure_increments_counter(self) -> None:
        """S1 network/HTTP error → s10_s1_lookup_failed_total counter incremented."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)  # cache miss
        s1 = _mock_s1(failure=True)

        cache = WatchlistCache(valkey, s1, ttl=300)
        with patch(_COUNTER_PATH) as mock_counter:
            result = await cache.get_watchers("entity-1")

        assert result == []
        mock_counter.inc.assert_called_once()

    @pytest.mark.unit
    async def test_s1_failure_logs_warning(self) -> None:
        """S1 failure → watchlist_s1_unavailable warning logged with entity_id."""
        from structlog.testing import capture_logs

        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)
        s1 = _mock_s1(failure=True)

        cache = WatchlistCache(valkey, s1, ttl=300)
        with capture_logs() as cap:
            with patch(_COUNTER_PATH):
                await cache.get_watchers("entity-99")

        assert any(
            e.get("event") == "watchlist_s1_unavailable" and e.get("entity_id") == "entity-99" for e in cap
        ), f"Expected warning not found in: {cap}"

    @pytest.mark.unit
    async def test_s1_empty_ok_no_counter(self) -> None:
        """S1 returns empty list (success) → counter NOT incremented."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)
        s1 = _mock_s1([])  # empty list, ok=True

        cache = WatchlistCache(valkey, s1, ttl=300)
        with patch(_COUNTER_PATH) as mock_counter:
            result = await cache.get_watchers("entity-1")

        assert result == []
        mock_counter.inc.assert_not_called()

    @pytest.mark.unit
    async def test_s1_success_cached(self) -> None:
        """S1 returns watchers (success) → result is cached in Valkey."""
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=None)
        watchers = [WatcherInfo("u1", "w1", ["SIGNAL"])]
        s1 = _mock_s1(watchers)

        cache = WatchlistCache(valkey, s1, ttl=300)
        with patch(_COUNTER_PATH) as mock_counter:
            result = await cache.get_watchers("entity-1")

        assert len(result) == 1
        assert result[0].user_id == "u1"
        mock_counter.inc.assert_not_called()
        valkey.set.assert_called_once()
