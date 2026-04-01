"""Integration tests — watchlist cache invalidation.

Tests:
  - cache miss → S1 called → result cached
  - cache hit → S1 not called
  - invalidate (item_deleted) → cache cleared → S1 called on next access
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ENTITY_ID = str(uuid4())
_USER_ID = str(uuid4())
_WATCHLIST_ID = str(uuid4())


@pytest.mark.integration
async def test_cache_miss_calls_s1_and_caches(
    watchlist_cache_fixture: Any,
    valkey_client: Any,
    httpserver: Any,
) -> None:
    """On cache miss the cache falls through to S1 and stores the result."""
    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{_ENTITY_ID}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": _ENTITY_ID,
            "watchers": [{"user_id": _USER_ID, "watchlist_id": _WATCHLIST_ID, "alert_types": []}],
        }
    )

    watchers = await watchlist_cache_fixture.get_watchers(_ENTITY_ID)
    assert len(watchers) == 1
    assert watchers[0].user_id == _USER_ID

    # Verify result is now cached in Valkey
    key = f"s10:v1:watchlist:by_entity:{_ENTITY_ID}"
    cached_raw = await valkey_client.get(key)
    assert cached_raw is not None
    cached = json.loads(cached_raw)
    assert cached[0]["user_id"] == _USER_ID


@pytest.mark.integration
async def test_cache_hit_skips_s1(
    watchlist_cache_fixture: Any,
    valkey_client: Any,
    httpserver: Any,
) -> None:
    """On cache hit S1 is not called."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    key = f"s10:v1:watchlist:by_entity:{entity_id}"

    # Pre-populate cache
    cached_data = json.dumps([{"user_id": user_id, "watchlist_id": str(uuid4()), "alert_types": []}])
    await valkey_client.set(key, cached_data, ex=300)

    # S1 is NOT configured — if called it would fail
    watchers = await watchlist_cache_fixture.get_watchers(entity_id)
    assert len(watchers) == 1
    assert watchers[0].user_id == user_id
    # httpserver.check_assertions() would pass — no S1 requests made


@pytest.mark.integration
async def test_invalidate_clears_cache(
    watchlist_cache_fixture: Any,
    valkey_client: Any,
    httpserver: Any,
) -> None:
    """After invalidate, next get_watchers hits S1 again (item_deleted pattern)."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    key = f"s10:v1:watchlist:by_entity:{entity_id}"

    # Pre-populate cache
    cached_data = json.dumps([{"user_id": user_id, "watchlist_id": str(uuid4()), "alert_types": []}])
    await valkey_client.set(key, cached_data, ex=300)

    # Invalidate (simulates watchlist item_deleted event from S1)
    await watchlist_cache_fixture.invalidate(entity_id)

    # Cache should be empty
    result = await valkey_client.get(key)
    assert result is None

    # S1 stub returns empty (no watchers for this entity after deletion)
    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json({"entity_id": entity_id, "watchers": []})

    watchers = await watchlist_cache_fixture.get_watchers(entity_id)
    assert watchers == []


@pytest.mark.integration
async def test_s1_failure_returns_empty(
    watchlist_cache_fixture: Any,
    httpserver: Any,
) -> None:
    """S1 errors degrade gracefully — empty result, no exception raised."""
    entity_id = str(uuid4())
    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_data("Internal Server Error", status=500)

    watchers = await watchlist_cache_fixture.get_watchers(entity_id)
    assert watchers == []
