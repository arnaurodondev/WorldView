"""Unit tests for upstream service HTTP client adapters (Wave E-3).

All tests verify the safe-degradation contract: every client method returns
an empty collection or None on timeout / HTTP errors — never raises.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import fakeredis.aioredis
import httpx
import pytest
from rag_chat.infrastructure.clients.s1_client import S1Client
from rag_chat.infrastructure.clients.s6_client import S6Client
from rag_chat.infrastructure.clients.s7_client import S7Client

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit

_BASE = "http://testservice"


# ── T1: S6 resolve_entities returns empty list on timeout ─────────────────────


@pytest.mark.asyncio
async def test_s6_client_resolve_returns_empty_on_timeout(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Timeout on POST /api/v1/entities/resolve → empty list, no exception raised."""
    httpx_mock.add_exception(httpx.TimeoutException("timeout"))

    client = S6Client(base_url=_BASE)
    result = await client.resolve_entities("Apple earnings Q3")

    assert result == []


# ── T2: S7 search_claims returns empty list on 5xx ────────────────────────────


@pytest.mark.asyncio
async def test_s7_client_claims_returns_empty_on_5xx(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """HTTP 503 on POST /api/v1/claims/search → empty list, no exception raised."""
    httpx_mock.add_response(status_code=503)

    entity_id = uuid4()
    client = S7Client(base_url=_BASE)
    result = await client.search_claims(entity_ids=[entity_id])

    assert result == []


# ── T3: S1 portfolio context served from Valkey cache on second call ──────────


@pytest.mark.asyncio
async def test_s1_client_portfolio_ctx_cached(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Second call to get_portfolio_context is served from Valkey — no second HTTP call."""
    user_id = uuid4()
    tenant_id = uuid4()
    token = "dev-internal-token"  # noqa: S105

    portfolio_payload = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "holdings": [{"ticker": "AAPL", "entity_id": str(uuid4()), "quantity": 10}],
        "watchlist": [],
        "total_positions": 1,
    }
    # Register ONE response — if S1Client calls HTTP twice the second call raises.
    httpx_mock.add_response(status_code=200, json=portfolio_payload)

    fake_valkey = fakeredis.aioredis.FakeRedis(decode_responses=False)
    client = S1Client(base_url=_BASE, valkey=fake_valkey)

    ctx1 = await client.get_portfolio_context(user_id, tenant_id, token)
    ctx2 = await client.get_portfolio_context(user_id, tenant_id, token)

    assert ctx1 is not None
    assert ctx2 is not None
    assert ctx1.user_id == ctx2.user_id == str(user_id)
    assert ctx1.total_positions == 1

    # Verify cached value is present in Valkey.
    raw = await fake_valkey.get(f"s1:v1:portfolio_ctx:{user_id}")
    assert raw is not None
    cached_data = json.loads(raw)
    assert cached_data["user_id"] == str(user_id)


# ── T4: S7 cypher_traverse returns empty list on 501 ─────────────────────────


@pytest.mark.asyncio
async def test_s7_cypher_501_returns_empty(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """HTTP 501 (feature disabled) on POST /api/v1/graph/cypher → empty list, no exception."""
    httpx_mock.add_response(status_code=501)

    client = S7Client(base_url=_BASE)
    result = await client.cypher_traverse(
        cypher="MATCH (n) RETURN n LIMIT 5",
        params={},
        max_results=5,
    )

    assert result == []


# ── T5: S7 cypher_traverse posts to /neighborhood endpoint (B-4 regression) ──


@pytest.mark.asyncio
async def test_cypher_traverse_uses_neighborhood_endpoint(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """cypher_traverse() must POST to /api/v1/graph/cypher/neighborhood, not /api/v1/graph/cypher."""
    import json

    entity_id = uuid4()
    httpx_mock.add_response(
        status_code=200,
        json={"center": {}, "relations": [{"relation_id": "r1"}], "entities": {}, "temporal_events": []},
    )

    client = S7Client(base_url=_BASE)
    result = await client.cypher_traverse(
        cypher="MATCH (e:Entity {id: $id})-[r*1..3]->(n) RETURN n",
        params={"id": str(entity_id)},
        max_results=30,
    )

    # Verify the result was parsed from "relations" key
    assert result == [{"relation_id": "r1"}]

    # Verify the correct endpoint was called
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert str(requests[0].url) == f"{_BASE}/api/v1/graph/cypher/neighborhood"

    # Verify the request body contains entity_id (not a raw cypher string)
    body = json.loads(requests[0].content)
    assert body["entity_id"] == str(entity_id)
    assert "cypher" not in body
