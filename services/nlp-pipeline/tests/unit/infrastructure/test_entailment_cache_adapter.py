"""Unit tests for ValkeyEntailmentCacheAdapter.

Invariants under test:
  - get() returns the deserialised dict on a hit.
  - get() returns None on a miss (get_json returns None).
  - get() returns None (never raises) when the underlying client errors — the
    fail-open contract the entailment blocks depend on.
  - get() returns None when get_json returns a non-dict payload (defensive).
  - set() forwards value + ttl to set_json.
  - set() swallows an underlying client error rather than raising.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.infrastructure.valkey.entailment_cache import (
    ValkeyEntailmentCacheAdapter,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_get_returns_cached_dict_on_hit() -> None:
    client = AsyncMock()
    client.get_json.return_value = {"entailed": True, "confidence": 0.9}
    adapter = ValkeyEntailmentCacheAdapter(client)
    result = await adapter.get("nlp:v1:entailment_cache:claim:abc")
    assert result == {"entailed": True, "confidence": 0.9}
    client.get_json.assert_awaited_once_with("nlp:v1:entailment_cache:claim:abc")


@pytest.mark.asyncio
async def test_get_returns_none_on_miss() -> None:
    client = AsyncMock()
    client.get_json.return_value = None
    adapter = ValkeyEntailmentCacheAdapter(client)
    assert await adapter.get("some-key") is None


@pytest.mark.asyncio
async def test_get_returns_none_on_client_error_fail_open() -> None:
    client = AsyncMock()
    client.get_json.side_effect = RuntimeError("valkey down")
    adapter = ValkeyEntailmentCacheAdapter(client)
    assert await adapter.get("some-key") is None


@pytest.mark.asyncio
async def test_get_returns_none_on_non_dict_payload() -> None:
    client = AsyncMock()
    client.get_json.return_value = "not-a-dict"
    adapter = ValkeyEntailmentCacheAdapter(client)
    assert await adapter.get("some-key") is None


@pytest.mark.asyncio
async def test_set_forwards_value_and_ttl() -> None:
    client = AsyncMock()
    adapter = ValkeyEntailmentCacheAdapter(client)
    payload: dict[str, Any] = {"asserted": False, "confidence": 0.95}
    await adapter.set("some-key", payload, 3600)
    client.set_json.assert_awaited_once_with("some-key", payload, ttl=3600)


@pytest.mark.asyncio
async def test_set_swallows_client_error() -> None:
    client = AsyncMock()
    client.set_json.side_effect = RuntimeError("valkey down")
    adapter = ValkeyEntailmentCacheAdapter(client)
    # Must not raise.
    await adapter.set("some-key", {"entailed": True, "confidence": 1.0}, 3600)
