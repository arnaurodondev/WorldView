"""Unit tests for UploadRateLimitAdapter (T-D-2-04).

PLAN-0086 Wave D-2: Verifies the INCR + EXPIRE rate-limit logic and the
fail-open behaviour when Valkey is unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from content_ingestion.infrastructure.valkey.upload_rate_limit import UploadRateLimitAdapter

import common.ids

pytestmark = pytest.mark.unit

_TENANT_ID = common.ids.new_uuid7()


def _make_valkey(*, incr_return: int = 1) -> AsyncMock:
    """Build an AsyncMock that mimics ValkeyClient's relevant methods."""
    client = AsyncMock()
    client.incr = AsyncMock(return_value=incr_return)
    client.expire = AsyncMock(return_value=True)
    client.ttl = AsyncMock(return_value=3600)
    return client


# ── T-D-2-04-01: allow under limit ───────────────────────────────────────────


class TestCheckAndIncrement:
    async def test_allow_under_limit(self) -> None:
        """Counter at 1 (first upload in window) → True (allow)."""
        client = _make_valkey(incr_return=1)
        adapter = UploadRateLimitAdapter(client)

        allowed = await adapter.check_and_increment(_TENANT_ID, window_seconds=86400, limit=50)

        assert allowed is True
        # INCR must be called with the correct key
        key = f"upload:v1:tenant:{_TENANT_ID}"
        client.incr.assert_awaited_once_with(key)
        # EXPIRE must be called when count == 1 (first write in window)
        client.expire.assert_awaited_once_with(key, 86400)

    async def test_allow_at_limit(self) -> None:
        """Counter exactly at the limit → True (still allowed)."""
        client = _make_valkey(incr_return=50)
        adapter = UploadRateLimitAdapter(client)

        allowed = await adapter.check_and_increment(_TENANT_ID, window_seconds=86400, limit=50)

        assert allowed is True
        # Not the first write (count != 1) → EXPIRE must NOT be called
        client.expire.assert_not_awaited()

    # ── T-D-2-04-02: block over limit ────────────────────────────────────────

    async def test_block_over_limit(self) -> None:
        """Counter exceeds the limit → False (blocked)."""
        client = _make_valkey(incr_return=51)
        adapter = UploadRateLimitAdapter(client)

        allowed = await adapter.check_and_increment(_TENANT_ID, window_seconds=86400, limit=50)

        assert allowed is False

    # ── T-D-2-04-03: fail-open on exception ──────────────────────────────────

    async def test_fail_open_on_exception(self) -> None:
        """Valkey raises ConnectionError → returns True (fail-open)."""
        client = AsyncMock()
        client.incr = AsyncMock(side_effect=ConnectionError("valkey down"))
        adapter = UploadRateLimitAdapter(client)

        # Must not raise and must return True
        allowed = await adapter.check_and_increment(_TENANT_ID, window_seconds=86400, limit=50)

        assert allowed is True


# ── get_reset_at ──────────────────────────────────────────────────────────────


class TestGetResetAt:
    async def test_returns_future_datetime_when_ttl_positive(self) -> None:
        """TTL=3600 → returns a datetime ~1 hour in the future."""
        client = _make_valkey()
        client.ttl = AsyncMock(return_value=3600)
        adapter = UploadRateLimitAdapter(client)

        reset_at = await adapter.get_reset_at(_TENANT_ID)

        assert reset_at is not None
        assert reset_at.tzinfo is not None  # must be UTC-aware

    async def test_returns_none_when_key_missing(self) -> None:
        """TTL=-2 (key missing) → returns None."""
        client = _make_valkey()
        client.ttl = AsyncMock(return_value=-2)
        adapter = UploadRateLimitAdapter(client)

        reset_at = await adapter.get_reset_at(_TENANT_ID)

        assert reset_at is None

    async def test_returns_none_on_exception(self) -> None:
        """Valkey raises → returns None (fail-safe)."""
        client = AsyncMock()
        client.ttl = AsyncMock(side_effect=ConnectionError("valkey down"))
        adapter = UploadRateLimitAdapter(client)

        reset_at = await adapter.get_reset_at(_TENANT_ID)

        assert reset_at is None
