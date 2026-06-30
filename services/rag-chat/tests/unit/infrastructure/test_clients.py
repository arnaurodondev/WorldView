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
async def test_s6_client_resolve_raises_transport_error_on_timeout(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Timeout on POST /api/v1/entities/resolve → ``UpstreamTransportError``.

    PLAN-0103 W2 BP-623 contract change: the legacy ``return []`` behaviour
    conflated outages with empty results. The base client now RAISES
    ``UpstreamTransportError(reason="upstream_timeout")``; the executor
    catches it and returns a ``TransportErrorMarker`` so the LLM can say
    "I cannot reach the upstream right now" instead of "no data was found".
    """
    from rag_chat.infrastructure.clients.base import UpstreamTransportError

    httpx_mock.add_exception(httpx.TimeoutException("timeout"))

    client = S6Client(base_url=_BASE)
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.resolve_entities("Apple earnings Q3")
    assert exc_info.value.reason == "upstream_timeout"


# ── T2: S7 search_claims returns empty list on 5xx ────────────────────────────


@pytest.mark.asyncio
async def test_s7_client_claims_raises_transport_error_on_5xx(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """HTTP 503 on POST /api/v1/claims/search → ``UpstreamTransportError``.

    PLAN-0103 W2 BP-623: 5xx now classifies as ``upstream_5xx`` so the
    orchestrator surfaces an outage, not an empty result.
    """
    from rag_chat.infrastructure.clients.base import UpstreamTransportError

    httpx_mock.add_response(status_code=503)

    entity_id = uuid4()
    client = S7Client(base_url=_BASE)
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.search_claims(entity_ids=[entity_id])
    assert exc_info.value.reason == "upstream_5xx"
    assert exc_info.value.status_code == 503


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
async def test_s7_cypher_501_raises_transport_error(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """HTTP 501 (feature disabled) → ``UpstreamTransportError`` (5xx family).

    PLAN-0103 W2 BP-623: 501 is in the 5xx server-error class; the base
    client now promotes it to ``upstream_5xx`` so the orchestrator emits
    ``status=transport_error`` instead of conflating it with an empty
    result. The "feature disabled" interpretation is preserved in the
    structured log + the LLM is told the source is unreachable.
    """
    from rag_chat.infrastructure.clients.base import UpstreamTransportError

    httpx_mock.add_response(status_code=501)

    client = S7Client(base_url=_BASE)
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.cypher_traverse(
            cypher="MATCH (n) RETURN n LIMIT 5",
            params={},
            max_results=5,
        )
    assert exc_info.value.reason == "upstream_5xx"
    assert exc_info.value.status_code == 501


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


# ── T6: ContentStoreClient resolves doc_id → source-article metadata ──────────


@pytest.mark.asyncio
async def test_content_store_client_resolves_document_metadata(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """feat/chat-kg-source-links: POST /api/v1/documents/batch → {doc_id: meta}.

    The map must carry the article URL + source + (parsed) published_at so the
    intelligence handler can backfill clickable KG citations.
    """
    from rag_chat.infrastructure.clients.content_store_client import ContentStoreClient

    doc_id = uuid4()
    httpx_mock.add_response(
        status_code=200,
        json={
            "documents": [
                {
                    "doc_id": str(doc_id),
                    "title": "Apple beats Q1",
                    "url": "https://news.example/apple",
                    "published_at": "2026-04-30T00:00:00+00:00",
                    "source_name": "Reuters",
                    "source_type": "news",
                    "word_count": 500,
                }
            ]
        },
    )

    client = ContentStoreClient(base_url=_BASE)
    result = await client.get_documents_metadata([doc_id])

    assert doc_id in result
    meta = result[doc_id]
    assert meta.url == "https://news.example/apple"
    assert meta.source_name == "Reuters"
    assert meta.published_at is not None and meta.published_at.year == 2026

    # Empty input short-circuits without an HTTP call.
    assert await client.get_documents_metadata([]) == {}
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert str(requests[0].url) == f"{_BASE}/api/v1/documents/batch"


@pytest.mark.asyncio
async def test_content_store_client_4xx_returns_empty_map(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """A 4xx (e.g. malformed request) degrades to an empty map, not an exception."""
    from rag_chat.infrastructure.clients.content_store_client import ContentStoreClient

    httpx_mock.add_response(status_code=400, json={"detail": "bad"})

    client = ContentStoreClient(base_url=_BASE)
    result = await client.get_documents_metadata([uuid4()])
    assert result == {}
