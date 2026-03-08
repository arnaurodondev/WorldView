"""Integration tests for ValkeyClient using fakeredis (no live instance required).

Tests cover every public method of ValkeyClient injecting a FakeRedis backend.
"""

from __future__ import annotations

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest

from messaging.valkey.client import ValkeyClient, ValkeyConfig

# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def client() -> ValkeyClient:  # type: ignore[return]
    """Return a ValkeyClient backed by an in-process FakeRedis store."""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    c = ValkeyClient(config=ValkeyConfig())
    c._redis = fake_redis  # type: ignore[assignment]
    yield c
    await fake_redis.close()


# ── Basic string operations ───────────────────────────────────────────────────


class TestBasicOperations:
    async def test_set_and_get(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "150.00")
        value = await client.get("md:v1:quote:AAPL")
        assert value == "150.00"

    async def test_get_missing_key_returns_none(self, client: ValkeyClient) -> None:
        assert await client.get("md:v1:quote:MISSING") is None

    async def test_set_with_ttl(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "150.00", ttl=60)
        remaining = await client.ttl("md:v1:quote:AAPL")
        assert 0 < remaining <= 60

    async def test_delete_existing_key(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "150.00")
        removed = await client.delete("md:v1:quote:AAPL")
        assert removed == 1
        assert await client.get("md:v1:quote:AAPL") is None

    async def test_delete_missing_key_returns_zero(self, client: ValkeyClient) -> None:
        assert await client.delete("md:v1:quote:NOPE") == 0

    async def test_exists_true(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "x")
        assert await client.exists("md:v1:quote:AAPL") is True

    async def test_exists_false(self, client: ValkeyClient) -> None:
        assert await client.exists("md:v1:quote:MISSING") is False

    async def test_expire_and_ttl(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "x")
        result = await client.expire("md:v1:quote:AAPL", 30)
        assert result is True
        remaining = await client.ttl("md:v1:quote:AAPL")
        assert 0 < remaining <= 30

    async def test_ttl_missing_key_returns_negative(self, client: ValkeyClient) -> None:
        ttl = await client.ttl("md:v1:quote:MISSING")
        assert ttl < 0


# ── JSON helpers ─────────────────────────────────────────────────────────────


class TestJsonOperations:
    async def test_set_json_and_get_json(self, client: ValkeyClient) -> None:
        payload = {"symbol": "AAPL", "price": 150.25, "volume": 1_000_000}
        await client.set_json("md:v1:quote:AAPL", payload, ttl=60)
        result = await client.get_json("md:v1:quote:AAPL")
        assert result == payload

    async def test_get_json_missing_key_returns_none(self, client: ValkeyClient) -> None:
        assert await client.get_json("md:v1:quote:MISSING") is None

    async def test_set_json_nested_structure(self, client: ValkeyClient) -> None:
        data = {"bar": {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0}}
        await client.set_json("md:v1:ohlcv:AAPL", data)
        result = await client.get_json("md:v1:ohlcv:AAPL")
        assert result == data

    async def test_set_json_overwrites_previous(self, client: ValkeyClient) -> None:
        await client.set_json("md:v1:quote:AAPL", {"price": 100.0})
        await client.set_json("md:v1:quote:AAPL", {"price": 200.0})
        result = await client.get_json("md:v1:quote:AAPL")
        assert result == {"price": 200.0}


# ── Batch operations ──────────────────────────────────────────────────────────


class TestBatchOperations:
    async def test_mset_and_mget(self, client: ValkeyClient) -> None:
        await client.mset({"k1": "v1", "k2": "v2", "k3": "v3"})
        results = await client.mget(["k1", "k2", "k3"])
        assert results == ["v1", "v2", "v3"]

    async def test_mget_partial_misses(self, client: ValkeyClient) -> None:
        await client.set("md:v1:quote:AAPL", "x")
        results = await client.mget(["md:v1:quote:AAPL", "md:v1:quote:MISSING"])
        assert results[0] == "x"
        assert results[1] is None

    async def test_delete_many(self, client: ValkeyClient) -> None:
        await client.mset({"a": "1", "b": "2", "c": "3"})
        removed = await client.delete_many(["a", "b", "c"])
        assert removed == 3
        assert await client.exists("a") is False

    async def test_delete_many_empty_list(self, client: ValkeyClient) -> None:
        assert await client.delete_many([]) == 0


# ── Hash operations ───────────────────────────────────────────────────────────


class TestHashOperations:
    async def test_hset_and_hget(self, client: ValkeyClient) -> None:
        await client.hset("md:v1:instrument:AAPL", "name", "Apple Inc.")
        value = await client.hget("md:v1:instrument:AAPL", "name")
        assert value == "Apple Inc."

    async def test_hget_missing_field_returns_none(self, client: ValkeyClient) -> None:
        await client.hset("md:v1:instrument:AAPL", "name", "Apple Inc.")
        assert await client.hget("md:v1:instrument:AAPL", "missing") is None

    async def test_hgetall(self, client: ValkeyClient) -> None:
        await client.hset("md:v1:instrument:AAPL", "name", "Apple Inc.")
        await client.hset("md:v1:instrument:AAPL", "sector", "Technology")
        data = await client.hgetall("md:v1:instrument:AAPL")
        assert data == {"name": "Apple Inc.", "sector": "Technology"}

    async def test_hdel_single_field(self, client: ValkeyClient) -> None:
        await client.hset("md:v1:instrument:AAPL", "name", "Apple Inc.")
        await client.hset("md:v1:instrument:AAPL", "sector", "Technology")
        await client.hdel("md:v1:instrument:AAPL", "sector")
        data = await client.hgetall("md:v1:instrument:AAPL")
        assert "sector" not in data
        assert "name" in data


# ── List operations ───────────────────────────────────────────────────────────


class TestListOperations:
    async def test_lpush_and_lrange(self, client: ValkeyClient) -> None:
        await client.lpush("nlp:v1:queue:articles", "article-3", "article-2", "article-1")
        items = await client.lrange("nlp:v1:queue:articles", 0, -1)
        assert len(items) == 3

    async def test_rpush_and_lrange(self, client: ValkeyClient) -> None:
        await client.rpush("nlp:v1:queue:articles", "a", "b", "c")
        items = await client.lrange("nlp:v1:queue:articles", 0, -1)
        assert items == ["a", "b", "c"]

    async def test_llen(self, client: ValkeyClient) -> None:
        await client.rpush("nlp:v1:queue:articles", "a", "b")
        assert await client.llen("nlp:v1:queue:articles") == 2

    async def test_lpop(self, client: ValkeyClient) -> None:
        await client.rpush("nlp:v1:queue:articles", "first", "second")
        item = await client.lpop("nlp:v1:queue:articles")
        assert item == "first"

    async def test_rpop(self, client: ValkeyClient) -> None:
        await client.rpush("nlp:v1:queue:articles", "first", "last")
        item = await client.rpop("nlp:v1:queue:articles")
        assert item == "last"

    async def test_lpop_empty_returns_none(self, client: ValkeyClient) -> None:
        assert await client.lpop("nlp:v1:queue:empty") is None


# ── Ping ──────────────────────────────────────────────────────────────────────


class TestPing:
    async def test_ping_returns_true(self, client: ValkeyClient) -> None:
        result = await client.ping()
        assert result is True
