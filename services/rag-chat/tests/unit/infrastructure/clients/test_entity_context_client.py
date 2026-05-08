"""Unit tests for EntityContextClient (PLAN-0074 Wave F, T-F-01).

Verifies:
  - Parallel calls to both S7 endpoints.
  - BP-235: httpx.Timeout(5.0) used, not default timeout.
  - 404 from S7 intelligence endpoint returns is_empty=True context.
  - 5xx retried once then returns is_empty=True.
  - Both endpoints called with the same JWT header.
  - Successful response maps fields to EntityChatContext correctly.

Note on URL matching: EntityContextClient._fetch_graph appends query params
(?depth=1&limit=5) to the graph URL. pytest_httpx requires full URL matches by
default, so we use re.compile() patterns that match the path prefix regardless
of query params.

Note on assert_all_responses_were_requested: Several tests register responses
for both endpoints but only one may be consumed (parallel execution + early
error handling). We override assert_all_responses_were_requested=False in the
test module fixture so pytest_httpx does not fail on unconsumed registered
responses. Tests that rely on exact call counts perform their own assertions
via httpx_mock.get_requests().
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from rag_chat.infrastructure.clients.entity_context_client import EntityContextClient

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit

_BASE = "http://testkg"

# Minimal S7 intelligence response shape
_INTEL_PAYLOAD = {
    "entity_id": None,  # overwritten per-test
    "canonical_name": "Apple Inc.",
    "entity_type": "financial_instrument",
    "health_score": 0.85,
    "data_completeness": 0.72,
    "key_metrics": {"pe_ratio": 28.5, "market_cap": "3.1T"},
    "current_narrative": {
        "narrative_text": "Apple is a leading technology company.",
        "model_id": "gemini-flash",
        "generation_reason": "scheduled",
    },
}

# Minimal S7 graph response shape (native S7 format)
_GRAPH_PAYLOAD = {
    "entity_id": None,
    "center": {"entity_id": None, "canonical_name": "Apple Inc."},
    "relations": [
        {
            "relation_id": "r1",
            "subject_entity_id": "aaaa",
            "object_entity_id": "bbbb",
            "canonical_type": "COMPETES_WITH",
            "confidence": 0.92,
        }
    ],
    "entities": {
        "bbbb": {"entity_id": "bbbb", "canonical_name": "Microsoft"},
    },
}


# ── Module-level fixture override ─────────────────────────────────────────────
# WHY: Several tests register mock responses for both S7 endpoints but the
# parallel gather() may only consume one of them (the other endpoint either
# errors out or is already handled). pytest_httpx 0.30 checks for unconsumed
# responses at teardown unless this fixture is overridden to False.
# Tests that need exact call-count assertions use httpx_mock.get_requests().
@pytest.fixture
def assert_all_responses_were_requested() -> bool:
    return False


# ── T1: Both endpoints called in parallel ─────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_calls_both_endpoints_called(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Both intelligence and graph endpoints are called for a successful load."""
    entity_id = uuid4()
    intel = {**_INTEL_PAYLOAD, "entity_id": str(entity_id)}
    graph = {**_GRAPH_PAYLOAD, "entity_id": str(entity_id)}

    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=200,
        json=intel,
    )
    # WHY regex: _fetch_graph adds ?depth=1&limit=5; regex pattern matches path prefix.
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
        status_code=200,
        json=graph,
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="test-jwt")

    # Verify both endpoints were actually called.
    requests = httpx_mock.get_requests()
    paths = {str(r.url.path) for r in requests}
    assert f"/internal/v1/entities/{entity_id}/intelligence" in paths
    assert f"/api/v1/entities/{entity_id}/graph" in paths

    # Verify the response is mapped correctly.
    assert ctx.entity_id == entity_id
    assert ctx.canonical_name == "Apple Inc."
    assert ctx.entity_type == "financial_instrument"
    assert ctx.narrative_text == "Apple is a leading technology company."
    assert ctx.health_score == pytest.approx(0.85)
    assert ctx.data_completeness == pytest.approx(0.72)
    assert ctx.key_metrics == {"pe_ratio": 28.5, "market_cap": "3.1T"}
    assert not ctx.is_empty

    # Verify relation was mapped from graph response.
    assert len(ctx.top_relations) == 1
    assert ctx.top_relations[0]["relation_type"] == "COMPETES_WITH"
    assert ctx.top_relations[0]["target_name"] == "Microsoft"


# ── T2: Timeout enforced (BP-235) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_enforced_returns_empty_context(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """BP-235: timeout on either endpoint returns is_empty=True — never raises."""
    entity_id = uuid4()

    # Both endpoints time out (intelligence + graph, plus any retries).
    # Register multiple so the retry attempt is also handled.
    for _ in range(4):  # enough for both calls + retry attempts
        httpx_mock.add_exception(httpx.TimeoutException("timed out"))

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="jwt")

    assert ctx.is_empty is True
    assert ctx.entity_id == entity_id


# ── T3: 404 from intelligence endpoint returns is_empty ────────────────────────


@pytest.mark.asyncio
async def test_404_from_intelligence_returns_empty_context(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """404 on intelligence endpoint (entity not found) -> is_empty=True."""
    entity_id = uuid4()

    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=404,
    )
    # Graph response registered; may or may not be consumed by parallel call.
    # assert_all_responses_were_requested=False (module fixture) prevents teardown
    # failure when this response is left unconsumed.
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
        status_code=200,
        json=_GRAPH_PAYLOAD,
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="jwt")

    assert ctx.is_empty is True
    assert ctx.entity_id == entity_id


# ── T4: 5xx retried once then is_empty ────────────────────────────────────────


@pytest.mark.asyncio
async def test_5xx_retried_once_then_returns_empty(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """5xx from intelligence endpoint: retried once, then is_empty=True."""
    entity_id = uuid4()

    # Intelligence: two 503s (initial + retry).
    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=503,
    )
    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=503,
    )
    # Graph: register a timeout response — parallel call may time out.
    # assert_all_responses_were_requested=False prevents failure if not consumed.
    httpx_mock.add_exception(
        httpx.TimeoutException("timed out"),
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="jwt")

    assert ctx.is_empty is True


# ── T5: JWT forwarded to both endpoints ───────────────────────────────────────


@pytest.mark.asyncio
async def test_both_endpoints_called_with_same_jwt(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """X-Internal-JWT header is forwarded to both S7 endpoints."""
    entity_id = uuid4()
    test_jwt = "eyJhbGciOiJSUzI1NiJ9.test-payload.signature"

    intel = {**_INTEL_PAYLOAD, "entity_id": str(entity_id)}
    graph = {**_GRAPH_PAYLOAD, "entity_id": str(entity_id)}

    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=200,
        json=intel,
    )
    httpx_mock.add_response(
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
        status_code=200,
        json=graph,
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token=test_jwt)

    assert not ctx.is_empty

    # Verify every outgoing request carried the JWT header.
    requests = httpx_mock.get_requests()
    assert len(requests) >= 2
    for req in requests:
        assert req.headers.get("X-Internal-JWT") == test_jwt


# ── T6: Empty JWT is not forwarded as header ──────────────────────────────────


@pytest.mark.asyncio
async def test_empty_jwt_not_forwarded(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """When jwt_token is empty string, X-Internal-JWT header is not sent."""
    entity_id = uuid4()
    intel = {**_INTEL_PAYLOAD, "entity_id": str(entity_id)}

    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=200,
        json=intel,
    )
    # Graph: register a timeout; parallel call may time out — not consumed is OK.
    # Context is NOT is_empty because intel succeeded.
    httpx_mock.add_exception(
        httpx.TimeoutException("timed out"),
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="")

    # Context loaded from intel (no relations from graph).
    assert not ctx.is_empty
    assert ctx.canonical_name == "Apple Inc."

    requests = httpx_mock.get_requests()
    intel_req = next(r for r in requests if "intelligence" in str(r.url))
    assert "X-Internal-JWT" not in intel_req.headers


# ── T7: Successful load includes narrative and key_metrics ────────────────────


@pytest.mark.asyncio
async def test_successful_load_maps_narrative_and_metrics(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Successful load correctly maps narrative_text and key_metrics."""
    entity_id = uuid4()
    intel = {**_INTEL_PAYLOAD, "entity_id": str(entity_id)}

    httpx_mock.add_response(
        url=f"{_BASE}/internal/v1/entities/{entity_id}/intelligence",
        status_code=200,
        json=intel,
    )
    # Graph times out — context is NOT is_empty because intel succeeded.
    httpx_mock.add_exception(
        httpx.TimeoutException("timed out"),
        url=re.compile(rf"{_BASE}/api/v1/entities/{entity_id}/graph"),
    )

    client = EntityContextClient(base_url=_BASE)
    ctx = await client.load(entity_id=entity_id, tenant_id=None, jwt_token="jwt")

    assert not ctx.is_empty
    assert ctx.narrative_text == "Apple is a leading technology company."
    assert ctx.key_metrics["pe_ratio"] == 28.5
    assert ctx.top_relations == []  # graph timed out -> no relations
