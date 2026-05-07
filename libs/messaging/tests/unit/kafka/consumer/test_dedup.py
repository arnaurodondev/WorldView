"""Unit tests for ValkeyDedupMixin (PLAN-0084 B-1, T-B-1-01).

Covers all behavioural contracts of the mixin:
- Happy-path duplicate detection and marking.
- None-client fallback (at-least-once mode).
- Valkey error resilience (never propagate to the consumer loop).
- Custom TTL configuration.
- Key prefix isolation.
- Concurrent-style consistency.
- Long event IDs (no truncation / overflow).

All tests use ``fakeredis.aioredis.FakeRedis`` for full in-process isolation —
no live Valkey instance required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest

from messaging.kafka.consumer.dedup import ValkeyDedupMixin
from messaging.valkey.client import ValkeyClient, ValkeyConfig

pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client() -> ValkeyClient:
    """Return a ValkeyClient backed by an in-process FakeRedis store."""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(config=ValkeyConfig())
    client._redis = fake_redis  # type: ignore[assignment]
    return client


def _make_mixin(
    client: ValkeyClient | None,
    prefix: str = "test:dedup:consumer",
    ttl: int = 86400,
) -> ValkeyDedupMixin:
    """Instantiate a bare ValkeyDedupMixin (not attached to a BaseKafkaConsumer).

    We test the mixin in isolation because its behaviour is entirely self-contained;
    it does not call any BaseKafkaConsumer methods.

    Creates a fresh anonymous subclass so that ClassVar _dedup_ttl_seconds can be
    set per-test without mutating the shared ValkeyDedupMixin class state.
    """
    # Build a per-call subclass so the ClassVar TTL stays isolated between tests.
    klass = type(
        "_TestMixin",
        (ValkeyDedupMixin,),
        {"_dedup_ttl_seconds": ttl},
    )
    mixin = klass()  # type: ignore[call-arg]
    mixin._dedup_client = client
    mixin._dedup_prefix = prefix
    return mixin  # type: ignore[return-value, no-any-return]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestIsDuplicate:
    async def test_is_duplicate_returns_True_when_key_exists(self) -> None:
        """After mark_processed the key must be detectable as duplicate."""
        client = _make_client()
        mixin = _make_mixin(client)

        await mixin.mark_processed("evt-001")
        result = await mixin.is_duplicate("evt-001")

        assert result is True

    async def test_is_duplicate_returns_False_when_key_absent(self) -> None:
        """A key that was never marked must not be treated as duplicate."""
        client = _make_client()
        mixin = _make_mixin(client)

        result = await mixin.is_duplicate("evt-999")

        assert result is False

    async def test_is_duplicate_returns_False_when_client_None(self) -> None:
        """When _dedup_client is None the mixin operates in at-least-once mode."""
        mixin = _make_mixin(client=None)

        result = await mixin.is_duplicate("evt-any")

        assert result is False

    async def test_is_duplicate_returns_False_on_valkey_error(self) -> None:
        """A Valkey failure must return False — never propagate to the consumer."""
        client = MagicMock(spec=ValkeyClient)
        client.exists = AsyncMock(side_effect=ConnectionError("valkey down"))
        mixin = _make_mixin(client=client)  # type: ignore[arg-type]

        result = await mixin.is_duplicate("evt-boom")

        # Must not raise; must default to False (at-least-once)
        assert result is False

    async def test_is_duplicate_does_not_cross_prefixes(self) -> None:
        """Keys from one prefix must not bleed into another prefix namespace."""
        client = _make_client()
        mixin_a = _make_mixin(client, prefix="svc:dedup:consumer_a")
        mixin_b = _make_mixin(client, prefix="svc:dedup:consumer_b")

        await mixin_a.mark_processed("shared-id")

        # mixin_b has a different prefix — must NOT see mixin_a's key
        assert await mixin_b.is_duplicate("shared-id") is False


class TestMarkProcessed:
    async def test_mark_processed_sets_24h_ttl(self) -> None:
        """Default TTL must be 86 400 seconds (24 hours)."""
        client = _make_client()
        mixin = _make_mixin(client)

        await mixin.mark_processed("evt-ttl")
        ttl = await client.ttl(f"{mixin._dedup_prefix}:evt-ttl")

        # TTL should be ≤ 86 400 and > 86 380 (allowing a tiny clock skew)
        assert 86_380 < ttl <= 86_400

    async def test_mark_processed_uses_prefix(self) -> None:
        """The stored Valkey key must follow the ``{prefix}:{event_id}`` convention."""
        client = _make_client()
        prefix = "nlp:dedup:article_consumer"
        mixin = _make_mixin(client, prefix=prefix)

        await mixin.mark_processed("evt-key-check")

        # Verify the key exists under the correct name
        assert await client.exists(f"{prefix}:evt-key-check") is True

    async def test_mark_processed_swallows_valkey_error(self) -> None:
        """A Valkey write failure must be swallowed — never propagate to caller."""
        client = MagicMock(spec=ValkeyClient)
        client.set = AsyncMock(side_effect=OSError("connection reset"))
        mixin = _make_mixin(client=client)  # type: ignore[arg-type]

        # Must not raise
        await mixin.mark_processed("evt-write-fail")

    async def test_mark_processed_noop_when_client_none(self) -> None:
        """When _dedup_client is None, mark_processed is a transparent no-op."""
        mixin = _make_mixin(client=None)

        # Must not raise and must not attempt any Valkey call
        await mixin.mark_processed("evt-noop")

    async def test_custom_ttl_seconds_respected(self) -> None:
        """When _dedup_ttl_seconds is overridden, the custom TTL must be used."""
        client = _make_client()
        custom_ttl = 3600  # 1 hour instead of 24
        mixin = _make_mixin(client, ttl=custom_ttl)

        await mixin.mark_processed("evt-custom-ttl")
        ttl = await client.ttl(f"{mixin._dedup_prefix}:evt-custom-ttl")

        assert 3580 < ttl <= 3600


class TestEdgeCases:
    async def test_concurrent_is_duplicate_returns_consistent_result(self) -> None:
        """Multiple concurrent is_duplicate calls on the same key must all agree."""
        client = _make_client()
        mixin = _make_mixin(client)

        await mixin.mark_processed("evt-concurrent")

        # Fire 10 concurrent checks
        results = await asyncio.gather(*[mixin.is_duplicate("evt-concurrent") for _ in range(10)])

        assert all(r is True for r in results), f"inconsistent results: {results}"

    async def test_long_event_id_does_not_overflow(self) -> None:
        """A 512-character event_id must be stored and retrieved without truncation."""
        client = _make_client()
        mixin = _make_mixin(client)
        long_id = "x" * 512

        await mixin.mark_processed(long_id)
        result = await mixin.is_duplicate(long_id)

        assert result is True

    async def test_separate_event_ids_independent(self) -> None:
        """Marking one event_id must not affect the dedup status of another."""
        client = _make_client()
        mixin = _make_mixin(client)

        await mixin.mark_processed("evt-A")

        assert await mixin.is_duplicate("evt-A") is True
        assert await mixin.is_duplicate("evt-B") is False
