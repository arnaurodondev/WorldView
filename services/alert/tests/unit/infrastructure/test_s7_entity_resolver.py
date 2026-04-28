"""Unit tests for S7EntityResolver — Valkey-cached lookup against S7.

Covers:
- Cache hit short-circuits the HTTP call.
- Cache miss → POST batch → cache + return.
- Negative cache for unknown entity_ids.
- HTTP failure returns ``(None, None)`` and DOES NOT cache.
- Corrupt cache entry treated as miss.

PLAN-0048 Wave B-1.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from alert.infrastructure.clients.s7_entity_resolver import S7EntityResolver


def _settings_stub(jwt: str = "fake.jwt", ttl: int = 900) -> MagicMock:
    """Return a Settings-like stub with only the fields the resolver reads."""
    s = MagicMock()
    s.s7_knowledge_graph_base_url = "http://kg.test"
    s.s7_internal_jwt = jwt
    s.entity_resolver_cache_ttl_seconds = ttl
    return s


def _mock_valkey() -> AsyncMock:
    """Return a Valkey client mock with default get/set AsyncMocks."""
    v = AsyncMock()
    v.get = AsyncMock(return_value=None)
    v.set = AsyncMock(return_value=True)
    return v


class TestS7EntityResolver:
    @pytest.mark.unit
    async def test_cache_hit_skips_http(self) -> None:
        """A cached ``[name, ticker]`` JSON list is returned without HTTP."""
        eid = uuid4()
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=json.dumps(["Apple Inc.", "AAPL"]).encode())

        # Build a transport that fails the test if hit — proves we don't HTTP.
        def _no_http(_: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP must not be called on cache hit")

        client = httpx.AsyncClient(transport=httpx.MockTransport(_no_http))
        resolver = S7EntityResolver(_settings_stub(), valkey, client=client)

        name, ticker = await resolver.resolve(eid)
        assert (name, ticker) == ("Apple Inc.", "AAPL")
        valkey.set.assert_not_called()
        await resolver.close()

    @pytest.mark.unit
    async def test_cache_miss_calls_s7_and_caches(self) -> None:
        """Cache miss → batch POST → result cached with TTL."""
        eid = uuid4()
        valkey = _mock_valkey()  # get returns None

        captured: dict[str, object] = {}

        def _handler(req: httpx.Request) -> httpx.Response:
            captured["url"] = str(req.url)
            captured["jwt"] = req.headers.get("X-Internal-JWT")
            captured["body"] = json.loads(req.content.decode())
            return httpx.Response(
                200,
                json={
                    "entities": [
                        {
                            "entity_id": str(eid),
                            "ticker": "TSLA",
                            "canonical_name": "Tesla, Inc.",
                        },
                    ],
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resolver = S7EntityResolver(_settings_stub(jwt="abc.jwt"), valkey, client=client)

        name, ticker = await resolver.resolve(eid)

        assert name == "Tesla, Inc."
        assert ticker == "TSLA"
        assert captured["url"] == "http://kg.test/api/v1/entities/batch"
        # Verifies X-Internal-JWT (PRD-0025) is forwarded — without it S7 returns 401.
        assert captured["jwt"] == "abc.jwt"
        # Single-element batch by entity_id.
        assert captured["body"] == {"entity_ids": [str(eid)]}
        # Cached as JSON tuple with the configured TTL.
        valkey.set.assert_called_once()
        args, kwargs = valkey.set.call_args
        assert args[0].endswith(str(eid))
        assert json.loads(args[1]) == ["Tesla, Inc.", "TSLA"]
        assert kwargs.get("ex") == 900
        await resolver.close()

    @pytest.mark.unit
    async def test_unknown_entity_returns_none_tuple_and_caches_negative(self) -> None:
        """S7 returns empty list → resolver returns (None, None) and caches it."""
        eid = uuid4()
        valkey = _mock_valkey()

        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"entities": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resolver = S7EntityResolver(_settings_stub(), valkey, client=client)

        result = await resolver.resolve(eid)
        assert result == (None, None)
        # Negative cache — a None-tuple is still cached so we don't retry-storm.
        valkey.set.assert_called_once()
        await resolver.close()

    @pytest.mark.unit
    async def test_http_error_returns_none_tuple_and_skips_cache(self) -> None:
        """Network/HTTP errors must NOT cache — upstream may recover."""
        eid = uuid4()
        valkey = _mock_valkey()

        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream unavailable")

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resolver = S7EntityResolver(_settings_stub(), valkey, client=client)

        result = await resolver.resolve(eid)
        assert result == (None, None)
        # No cache write on error so we retry on the next alert.
        valkey.set.assert_not_called()
        await resolver.close()

    @pytest.mark.unit
    async def test_corrupt_cache_entry_treated_as_miss(self) -> None:
        """Malformed JSON in cache must not propagate — treat as miss + refetch."""
        eid = uuid4()
        valkey = _mock_valkey()
        valkey.get = AsyncMock(return_value=b"not-valid-json{")

        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"entities": [{"entity_id": str(eid), "ticker": "X", "canonical_name": "X Co."}]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resolver = S7EntityResolver(_settings_stub(), valkey, client=client)

        name, ticker = await resolver.resolve(eid)
        assert (name, ticker) == ("X Co.", "X")
        await resolver.close()

    @pytest.mark.unit
    async def test_cache_get_failure_falls_through_to_http(self) -> None:
        """Valkey GET raising must fall through to HTTP, never raise."""
        eid = uuid4()
        valkey = _mock_valkey()
        valkey.get = AsyncMock(side_effect=RuntimeError("valkey down"))

        def _handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"entities": [{"entity_id": str(eid), "ticker": "Y", "canonical_name": "Y Co."}]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resolver = S7EntityResolver(_settings_stub(), valkey, client=client)

        result = await resolver.resolve(eid)
        # Resolver doesn't raise — degrades to a direct HTTP lookup.
        assert result == ("Y Co.", "Y")
        await resolver.close()
