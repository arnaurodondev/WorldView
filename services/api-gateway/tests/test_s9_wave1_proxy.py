"""Tests for PRD-0028 Wave S9-1 proxy routes (OHLCV, Quotes, Fundamentals,
Entity Graph, Contradictions, News, Briefings).

Uses the shared conftest fixtures:
- ``app`` / ``mock_clients`` for unauthenticated routes and 401 tests
- ``authed_app`` / ``authed_mock_clients`` for authenticated route tests
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}

# WHY valid UUID: instrument_id path params are now UUID-typed (F-010 security fix).
# FastAPI auto-validates and returns 422 for non-UUID values before route logic runs.
_INSTRUMENT_UUID = "11111111-1111-1111-1111-111111111111"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    import json as _json

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    # WHY: proxy code calls resp.json() to parse the body; MagicMock.spec=httpx.Response
    # creates a stub that returns another MagicMock by default. Provide the actual
    # parsed dict so JSON serialisation in the proxy doesn't fail.
    try:
        resp.json = MagicMock(return_value=_json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


def _inject_rsa_keys(application) -> None:
    """Inject real RSA keys into app state so _system_headers() can issue JWTs."""
    from api_gateway.oidc import rsa_key_id

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    application.state.rsa_private_key = private_key
    application.state.rsa_public_key = private_key.public_key()
    application.state.rsa_kid = rsa_key_id(private_key.public_key())


# ── OHLCV ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohlcv_proxy_requires_auth(app, mock_clients) -> None:
    """GET /v1/ohlcv/{id} without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/ohlcv/{_INSTRUMENT_UUID}")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_ohlcv_proxy_forwards_query_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id}?period=1d forwards query params to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"bars": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/ohlcv/{_INSTRUMENT_UUID}",
            params={"period": "1d", "from": "2026-01-01"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("period") == "1d"
    assert call_kwargs["params"].get("from") == "2026-01-01"


@pytest.mark.asyncio
async def test_ohlcv_proxy_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id} with valid JWT → 200 proxied from S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"bars": [{"o": 100}]}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/ohlcv/{_INSTRUMENT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert f"/api/v1/ohlcv/{_INSTRUMENT_UUID}" in call_args[0]


# ── Quotes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quotes_single_proxy_fallback(authed_app, authed_mock_clients) -> None:
    """GET /v1/quotes/{id} falls back to legacy S3 quote endpoint when PriceSnapshot returns 404.

    PLAN-0036 W1-10: the route first tries /internal/v1/price/{id}; on 404 it
    falls back to /api/v1/quotes/{id}. When PriceSnapshot is not yet deployed
    (or no snapshot exists), the user still gets a valid response from the
    legacy path.
    """

    def _side_effect(path: str, **kwargs: object) -> object:
        if "/internal/v1/price/" in path:
            return _mock_response(404, b'{"detail": "not found"}')
        # legacy quote path
        legacy = (
            b'{"instrument_id": "instr-1", "last": "150.0", "bid": null,'
            b' "ask": null, "volume": null, "timestamp": "2026-04-24T00:00:00Z",'
            b' "updated_at": "2026-04-24T00:00:00Z"}'
        )
        return _mock_response(200, legacy)

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_side_effect)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/quotes/{_INSTRUMENT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # Two calls: first to PriceSnapshot (404), then to legacy quote endpoint
    assert authed_mock_clients.market_data.get.call_count == 2
    calls = [c[0][0] for c in authed_mock_clients.market_data.get.call_args_list]
    assert any(f"/internal/v1/price/{_INSTRUMENT_UUID}" in c for c in calls)
    assert any(f"/api/v1/quotes/{_INSTRUMENT_UUID}" in c for c in calls)


@pytest.mark.asyncio
async def test_quotes_single_proxy_price_snapshot(authed_app, authed_mock_clients) -> None:
    """GET /v1/quotes/{id} returns enriched quote when PriceSnapshot succeeds.

    PLAN-0036 W1-10: when S3 /internal/v1/price/{id} returns a valid
    PriceSnapshotResponse, the enriched quote (with freshness_status, source,
    etc.) is returned directly — the legacy endpoint is NOT called.
    """
    import json

    snapshot = {
        "instrument_id": "instr-1",
        "symbol": "AAPL",
        "exchange": "US",
        "price": "150.00",
        "price_change": "2.50",
        "price_change_pct": "1.69",
        "timestamp": "2026-04-24T15:00:00Z",
        "fetched_at": "2026-04-24T15:01:00Z",
        "source": "fresh_quote",
        "freshness_status": "live",
        "stale_reason": None,
        "refresh_available": True,
        "refresh_cooldown_remaining_sec": 0,
    }
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(snapshot).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/quotes/{_INSTRUMENT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Enriched freshness fields must be present
    assert body["freshness_status"] == "live"
    assert body["source"] == "fresh_quote"
    assert body["price"] == 150.0
    # Only one call (PriceSnapshot succeeded — no fallback needed)
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_quotes_batch_body_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/quotes/batch forwards request body to the S3 legacy endpoint.

    PLAN-0036 W1-10: the route first tries /internal/v1/price/batch (PriceSnapshot
    batch). When that returns 404 (not yet deployed), it falls back to the legacy
    /api/v1/quotes/batch endpoint. This test verifies the body is forwarded correctly
    to the legacy endpoint on the fallback path.
    """

    def _side_effect(path: str, **kwargs: object) -> object:
        if "/internal/v1/price/batch" in path:
            return _mock_response(404, b'{"detail": "not found"}')
        # legacy batch quote path
        return _mock_response(200, b'{"quotes": []}')

    authed_mock_clients.market_data.post = AsyncMock(side_effect=_side_effect)

    body = b'{"instrument_ids": ["instr-1", "instr-2"]}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/quotes/batch",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    # Two calls: PriceSnapshot batch (404) then legacy batch endpoint
    assert authed_mock_clients.market_data.post.call_count == 2
    calls = authed_mock_clients.market_data.post.call_args_list
    # Verify the body was forwarded to both endpoints (same body used in fallback)
    legacy_call = next(c for c in calls if "/api/v1/quotes/batch" in c[0][0])
    assert legacy_call[1]["content"] == body


# ── Fundamentals ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fundamentals_proxy_unauthenticated(app, mock_clients) -> None:
    """GET /v1/fundamentals/{id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_fundamentals_proxy_forwards_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}?fields=pe_ratio forwards query params to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"pe_ratio": 25.0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}",
            params={"fields": "pe_ratio"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("fields") == "pe_ratio"
    # Verify downstream path includes instrument_id
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert f"/api/v1/fundamentals/{_INSTRUMENT_UUID}" in call_args[0]


# ── Entity Graph + Contradictions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_graph_depth_param(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph?depth=2 forwards depth param to S7.

    The response is transformed from S7's GraphNeighborhoodResponse to the
    frontend EntityGraph format by _transform_graph_response() in the route
    handler. The mock must return a valid S7 payload so the transform succeeds.
    """
    entity_id = "00000000-0000-0000-0000-000000000001"

    # Provide a minimal but valid S7 GraphNeighborhoodResponse so the gateway's
    # _transform_graph_response() can parse it without raising TypeError.
    s7_payload = {
        "center": {"entity_id": entity_id, "canonical_name": "Test Corp.", "entity_type": "company"},
        "relations": [],
        "entities": {},
    }
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = s7_payload

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=mock_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            params={"depth": "2"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # ISSUE-5 fix (2026-05-10): depth IS now forwarded to S7.
    # BP-S9-GRAPH-001 (depth>1 merge): the handler makes TWO S7 calls when depth>1 —
    # the primary call with the requested depth, then a depth=1 SQL call to merge in
    # direct-neighbor edges (AGE only returns depth-N neighbors but the `relations` list
    # is always depth=1, so depth=2 graphs had no edges without the merge).
    # call_args_list[0] = primary (depth=2), call_args_list[1] = merge (depth=1).
    assert authed_mock_clients.knowledge_graph.get.call_count == 2
    first_call_kwargs = authed_mock_clients.knowledge_graph.get.call_args_list[0][1]
    assert "depth" in first_call_kwargs["params"], "depth must be forwarded to S7 when >1 (ISSUE-5)"
    assert first_call_kwargs["params"]["depth"] == "2", "depth value must be forwarded as string"
    assert "limit" in first_call_kwargs["params"], "limit is always forwarded to S7"
    first_call_args = authed_mock_clients.knowledge_graph.get.call_args_list[0][0]
    assert f"/api/v1/entities/{entity_id}/graph" in first_call_args[0]
    # Second call is the depth=1 merge — must NOT include depth param.
    second_call_kwargs = authed_mock_clients.knowledge_graph.get.call_args_list[1][1]
    assert "depth" not in second_call_kwargs["params"], "merge call must use SQL path (no depth)"
    # Verify response is transformed to EntityGraph format (not raw S7 shape)
    body = resp.json()
    assert "entity_id" in body
    assert "nodes" in body
    assert "edges" in body


@pytest.mark.asyncio
async def test_transform_graph_response_orphan_filter() -> None:
    """_transform_graph_response strips orphan edges and orphan nodes.

    F-001: the orphan filter logic is pure and testable without an HTTP stack.
    Two cases:
    (a) an edge referencing an entity_id absent from the nodes dict is removed
    (b) a node that only appeared as an edge endpoint — now removed — becomes
        orphaned and is also removed (unless it is the center entity).
    """
    from api_gateway.routes.intelligence import _transform_graph_response

    center_id = "00000000-0000-0000-0000-000000000001"
    connected_id = "00000000-0000-0000-0000-000000000002"
    ghost_id = "00000000-0000-0000-0000-000000000099"  # in entities but in no relation

    s7_payload = {
        "center": {"entity_id": center_id, "canonical_name": "Center Co.", "entity_type": "company"},
        "relations": [
            {
                "relation_id": "rel-1",
                "subject_entity_id": center_id,
                "object_entity_id": connected_id,
                "canonical_type": "competes_with",
                "confidence": 0.8,
                "decay_class": "DURABLE",
                "relation_summary": None,
            },
            # Edge whose object is absent from entities dict → must be filtered out.
            {
                "relation_id": "rel-ghost",
                "subject_entity_id": center_id,
                "object_entity_id": ghost_id,
                "canonical_type": "partner_of",
                "confidence": 0.7,
                "decay_class": "MEDIUM",
                "relation_summary": None,
            },
        ],
        "entities": {
            connected_id: {"entity_id": connected_id, "canonical_name": "Connected Co.", "entity_type": "company"},
            # ghost_id deliberately absent — simulates AGE returning entity_id not in entities dict.
        },
    }

    result = _transform_graph_response(s7_payload)

    node_ids = {n["id"] for n in result["nodes"]}
    edge_ids = {e["id"] for e in result["edges"]}

    # Center must always be present.
    assert center_id in node_ids
    # Connected node (has a valid edge) must be present.
    assert connected_id in node_ids
    # Ghost id was absent from entities dict → its edge and itself must be absent.
    assert ghost_id not in node_ids
    assert "rel-ghost" not in edge_ids
    # Valid edge must remain.
    assert "rel-1" in edge_ids


@pytest.mark.asyncio
async def test_transform_graph_b01_optional_fields_on_nodes() -> None:
    """_transform_graph_response propagates B-01 optional fields on center and neighbor nodes.

    F-007: ticker, description, sector are forwarded from S7 EntitySummary so
    the frontend InlineSelectionPanel and PeerComparisonPanel can use them
    without a second API call.  None is the correct sentinel when the field is
    absent — NOT an empty string.
    """
    from api_gateway.routes.intelligence import _transform_graph_response

    center_id = "00000000-0000-0000-0000-000000000001"
    neighbor_id = "00000000-0000-0000-0000-000000000002"

    s7_payload = {
        "center": {
            "entity_id": center_id,
            "canonical_name": "Apple Inc.",
            "entity_type": "company",
            "ticker": "AAPL",
            "description": "Technology company.",
            "sector": "Technology",
        },
        "relations": [
            {
                "relation_id": "rel-1",
                "subject_entity_id": center_id,
                "object_entity_id": neighbor_id,
                "canonical_type": "competes_with",
                "confidence": 0.85,
            }
        ],
        "entities": {
            neighbor_id: {
                "entity_id": neighbor_id,
                "canonical_name": "Microsoft Corp.",
                "entity_type": "company",
                "ticker": "MSFT",
                "description": "Software company.",
                "sector": "Technology",
            }
        },
    }

    result = _transform_graph_response(s7_payload)

    nodes_by_id = {n["id"]: n for n in result["nodes"]}

    # Center node B-01 fields
    center_node = nodes_by_id[center_id]
    assert center_node["ticker"] == "AAPL", "center ticker must be forwarded"
    assert center_node["description"] == "Technology company.", "center description must be forwarded"
    assert center_node["sector"] == "Technology", "center sector must be forwarded"

    # Neighbor node B-01 fields
    neighbor_node = nodes_by_id[neighbor_id]
    assert neighbor_node["ticker"] == "MSFT", "neighbor ticker must be forwarded"
    assert neighbor_node["description"] == "Software company.", "neighbor description must be forwarded"
    assert neighbor_node["sector"] == "Technology", "neighbor sector must be forwarded"


@pytest.mark.asyncio
async def test_transform_graph_b01_optional_fields_absent_when_missing() -> None:
    """_transform_graph_response sets description and sector to None when S7 omits them.

    F-007: optional B-01 fields must be None (not empty string) when absent —
    the frontend type contract uses null/undefined to conditionally render panels.
    ticker defaults to empty string (non-nullable in the frontend type).
    """
    from api_gateway.routes.intelligence import _transform_graph_response

    center_id = "00000000-0000-0000-0000-000000000010"
    neighbor_id = "00000000-0000-0000-0000-000000000011"

    s7_payload = {
        "center": {
            "entity_id": center_id,
            "canonical_name": "No-Meta Corp.",
            "entity_type": "company",
            # ticker, description, sector intentionally absent
        },
        "relations": [
            {
                "relation_id": "rel-nm",
                "subject_entity_id": center_id,
                "object_entity_id": neighbor_id,
                "canonical_type": "partner_of",
                "confidence": 0.7,
            }
        ],
        "entities": {
            neighbor_id: {
                "entity_id": neighbor_id,
                "canonical_name": "Also No Meta.",
                "entity_type": "company",
                # B-01 fields absent
            }
        },
    }

    result = _transform_graph_response(s7_payload)
    nodes_by_id = {n["id"]: n for n in result["nodes"]}

    center_node = nodes_by_id[center_id]
    assert center_node["description"] is None, "description must be None when absent from S7"
    assert center_node["sector"] is None, "sector must be None when absent from S7"
    assert center_node["ticker"] == "", "ticker must default to empty string when absent"

    neighbor_node = nodes_by_id[neighbor_id]
    assert neighbor_node["description"] is None
    assert neighbor_node["sector"] is None
    assert neighbor_node["ticker"] == ""


@pytest.mark.asyncio
async def test_transform_graph_edge_decay_class_forwarded() -> None:
    """_transform_graph_response forwards decay_class from S7 relation to edge.

    F-007 / B-02: decay_class drives edge opacity in the sigma edgeReducer
    (PERMANENT/DURABLE=1.0, SLOW/MEDIUM=0.7, FAST/EPHEMERAL=0.4).
    When S7 omits it the edge must carry decay_class=None so the frontend
    falls back to MEDIUM opacity without raising a KeyError.
    """
    from api_gateway.routes.intelligence import _transform_graph_response

    center_id = "00000000-0000-0000-0000-000000000020"
    neighbor_a = "00000000-0000-0000-0000-000000000021"
    neighbor_b = "00000000-0000-0000-0000-000000000022"

    s7_payload = {
        "center": {"entity_id": center_id, "canonical_name": "Center", "entity_type": "company"},
        "relations": [
            {
                "relation_id": "rel-durable",
                "subject_entity_id": center_id,
                "object_entity_id": neighbor_a,
                "canonical_type": "owns",
                "confidence": 0.9,
                "decay_class": "DURABLE",
            },
            {
                "relation_id": "rel-no-decay",
                "subject_entity_id": center_id,
                "object_entity_id": neighbor_b,
                "canonical_type": "partner_of",
                "confidence": 0.6,
                # decay_class intentionally absent
            },
        ],
        "entities": {
            neighbor_a: {"entity_id": neighbor_a, "canonical_name": "Neighbor A", "entity_type": "company"},
            neighbor_b: {"entity_id": neighbor_b, "canonical_name": "Neighbor B", "entity_type": "company"},
        },
    }

    result = _transform_graph_response(s7_payload)
    edges_by_id = {e["id"]: e for e in result["edges"]}

    # decay_class present in S7 → forwarded to edge
    assert edges_by_id["rel-durable"]["decay_class"] == "DURABLE"
    # decay_class absent in S7 → None on edge (not missing key, not empty string)
    assert "decay_class" in edges_by_id["rel-no-decay"], "decay_class key must always be present on edge"
    assert edges_by_id["rel-no-decay"]["decay_class"] is None


@pytest.mark.asyncio
async def test_transform_graph_edge_direction_outbound_inbound_lateral() -> None:
    """_transform_graph_response sets direction=outbound/inbound/lateral correctly.

    F-007: direction encodes the semantic role of center vs endpoint:
    - outbound: center is the subject (the initiating/owning side)
    - inbound: center is the object (the receiving side)
    - lateral: neither endpoint is the center (depth>1 cross-edges)
    """
    from api_gateway.routes.intelligence import _transform_graph_response

    center_id = "00000000-0000-0000-0000-000000000030"
    neighbor_a = "00000000-0000-0000-0000-000000000031"
    neighbor_b = "00000000-0000-0000-0000-000000000032"

    s7_payload = {
        "center": {"entity_id": center_id, "canonical_name": "Center", "entity_type": "company"},
        "relations": [
            # center→neighbor_a: outbound (center is subject)
            {
                "relation_id": "rel-out",
                "subject_entity_id": center_id,
                "object_entity_id": neighbor_a,
                "canonical_type": "employs",
                "confidence": 0.9,
            },
            # neighbor_b→center: inbound (center is object)
            {
                "relation_id": "rel-in",
                "subject_entity_id": neighbor_b,
                "object_entity_id": center_id,
                "canonical_type": "acquired_by",
                "confidence": 0.8,
            },
            # neighbor_a→neighbor_b: lateral (neither endpoint is center)
            {
                "relation_id": "rel-lat",
                "subject_entity_id": neighbor_a,
                "object_entity_id": neighbor_b,
                "canonical_type": "partner_of",
                "confidence": 0.7,
            },
        ],
        "entities": {
            neighbor_a: {"entity_id": neighbor_a, "canonical_name": "Neighbor A", "entity_type": "company"},
            neighbor_b: {"entity_id": neighbor_b, "canonical_name": "Neighbor B", "entity_type": "company"},
        },
    }

    result = _transform_graph_response(s7_payload)
    edges_by_id = {e["id"]: e for e in result["edges"]}

    assert edges_by_id["rel-out"]["direction"] == "outbound", "center as subject → direction must be outbound"
    assert edges_by_id["rel-in"]["direction"] == "inbound", "center as object → direction must be inbound"
    assert edges_by_id["rel-lat"]["direction"] == "lateral", "neither endpoint is center → direction must be lateral"


@pytest.mark.asyncio
async def test_entity_graph_depth1_merge_with_real_data(authed_app, authed_mock_clients) -> None:
    """depth>1 merge integrates depth=1 nodes+edges into the primary result.

    F-002: the previous test used empty payloads so the merge loop never ran.
    This test uses payloads where depth=2 returns only a depth-2 orphan node
    and depth=1 returns the connected neighbor — verifying that after merge the
    depth-1 neighbor and its edge are present in the final response.
    """
    entity_id = "00000000-0000-0000-0000-000000000001"
    depth2_entity = "00000000-0000-0000-0000-000000000002"
    depth1_entity = "00000000-0000-0000-0000-000000000003"

    # depth=2 primary call: returns a depth-2 node with NO relations (AGE bug).
    depth2_payload = {
        "center": {"entity_id": entity_id, "canonical_name": "Center", "entity_type": "company"},
        "relations": [],  # no edges → depth2_entity becomes an orphan after filter
        "entities": {
            depth2_entity: {"entity_id": depth2_entity, "canonical_name": "Depth2 Co.", "entity_type": "company"},
        },
    }
    # depth=1 merge call: returns the direct neighbor with 1 edge.
    depth1_payload = {
        "center": {"entity_id": entity_id, "canonical_name": "Center", "entity_type": "company"},
        "relations": [
            {
                "relation_id": "rel-d1",
                "subject_entity_id": entity_id,
                "object_entity_id": depth1_entity,
                "canonical_type": "employs",
                "confidence": 0.9,
                "decay_class": "PERMANENT",
                "relation_summary": None,
            }
        ],
        "entities": {
            depth1_entity: {"entity_id": depth1_entity, "canonical_name": "Depth1 Co.", "entity_type": "company"},
        },
    }

    def _make_resp(payload: dict) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = payload
        return r

    authed_mock_clients.knowledge_graph.get = AsyncMock(
        side_effect=[_make_resp(depth2_payload), _make_resp(depth1_payload)]
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            params={"depth": "2"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    edge_ids = {e["id"] for e in body["edges"]}

    # Center must always be present.
    assert entity_id in node_ids
    # depth=1 entity must be present after merge (it has a valid edge).
    assert depth1_entity in node_ids
    # depth=2 entity had no edges → orphan filter removes it even after merge.
    assert depth2_entity not in node_ids
    # The depth=1 edge must be present.
    assert "rel-d1" in edge_ids


@pytest.mark.asyncio
async def test_entity_contradictions_proxy(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/contradictions proxied to S7."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"contradictions": []}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000002"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/contradictions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_args = authed_mock_clients.knowledge_graph.get.call_args[0]
    assert f"/api/v1/entities/{entity_id}/contradictions" in call_args[0]


# ── News ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_news_top_no_auth_required(app, mock_clients) -> None:
    """GET /v1/news/top works without authentication (public endpoint, PRD-0026 §6.7 Flow C)."""
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"hours": "24", "limit": "10"})

    assert resp.status_code == 200
    mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = mock_clients.nlp_pipeline.get.call_args
    # Verify path targets S6 NLP Pipeline (not S5 Content Store).
    assert "/api/v1/news/top" in call_args[0][0]
    call_kwargs = call_args[1]
    assert call_kwargs["params"].get("hours") == "24"
    assert call_kwargs["params"].get("limit") == "10"


@pytest.mark.asyncio
async def test_news_entity_requires_auth(app, mock_clients) -> None:
    """GET /v1/news/entity/{id} without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/news/entity/{entity_id}")

    assert resp.status_code == 401
    mock_clients.nlp_pipeline.get.assert_not_called()


# ── Briefings ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_briefings_morning_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/morning without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/briefings/morning")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()


@pytest.mark.asyncio
async def test_briefings_morning_proxied(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning proxied to S8 rag-chat."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, b'{"briefing": "Good morning..."}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args[0]
    assert "/api/v1/briefings/morning" in call_args[0]


# ── F-002: Downstream error handling ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohlcv_proxy_downstream_500(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id} when S3 returns 500 → 500 forwarded transparently."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/ohlcv/{_INSTRUMENT_UUID}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_entity_graph_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph when S7 returns 503 → 503 forwarded."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    authed_mock_clients.knowledge_graph.get.assert_called_once()


@pytest.mark.asyncio
async def test_news_top_downstream_error(app, mock_clients) -> None:
    """GET /v1/news/top when S6 returns 502 → 502 forwarded (public endpoint)."""
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(502, b'{"detail": "Bad Gateway"}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top")

    assert resp.status_code == 502
    mock_clients.nlp_pipeline.get.assert_called_once()


@pytest.mark.asyncio
async def test_briefings_morning_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning when S8 returns 503 → 503 forwarded."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    authed_mock_clients.rag_chat.get.assert_called_once()


# ── F-007: Briefings/instrument tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_briefings_instrument_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/instrument/{id} without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/briefings/instrument/{entity_id}")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()


@pytest.mark.asyncio
async def test_briefings_instrument_proxied(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/instrument/{id} with auth → proxied to S8."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, b'{"briefing": "AAPL analysis..."}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/briefings/instrument/{entity_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args[0]
    assert f"/api/v1/briefings/instrument/{entity_id}" in call_args[0]


# ── F-013: News/entity authenticated test ───────────────────────────────────


@pytest.mark.asyncio
async def test_news_entity_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/news/entity/{id} with auth → proxied to S6 as path param (PRD-0026 §6.7 Flow D)."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": [], "total": 0}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/news/entity/{entity_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = authed_mock_clients.nlp_pipeline.get.call_args[0]
    # Verify entity_id is a path segment, NOT a query param (BP-026 guard).
    assert f"/api/v1/entities/{entity_id}/articles" in call_args[0]
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert "entity_id" not in call_kwargs.get("params", {})


# ── F-014: /v1/entities/{entity_id}/articles canonical alias ─────────────────


@pytest.mark.asyncio
async def test_entity_articles_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/articles without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{entity_id}/articles")

    assert resp.status_code == 401
    mock_clients.nlp_pipeline.get.assert_not_called()


@pytest.mark.asyncio
async def test_entity_articles_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/articles with auth → proxied to S6 entity articles endpoint.

    This is the canonical path alias for /v1/news/entity/{id}.  Both routes proxy
    to S6's GET /api/v1/entities/{entity_id}/articles endpoint.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": [], "total": 0}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000002"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/articles",
            params={"limit": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = authed_mock_clients.nlp_pipeline.get.call_args[0]
    # Verify entity_id is a path segment routed to S6's entity articles endpoint.
    assert f"/api/v1/entities/{entity_id}/articles" in call_args[0]
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    # Verify entity_id is NOT leaked as a query parameter.
    assert "entity_id" not in call_kwargs.get("params", {})


# ── F-02: Public proxy routes forward system JWT headers ──────────────────────


@pytest.mark.asyncio
async def test_news_top_sends_system_jwt_header(app, mock_clients) -> None:
    """F-02: GET /v1/news/top (public) sends X-Internal-JWT system header to S6 (nlp-pipeline).

    Route was changed from S5 (content-store) to S6 (nlp-pipeline) in PLAN-0029.
    """
    _inject_rsa_keys(app)
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"limit": "5"})

    assert resp.status_code == 200
    # Verify X-Internal-JWT was sent to the downstream S6 endpoint
    call_kwargs = mock_clients.nlp_pipeline.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})
    # Verify the JWT is decodable and has system claims
    from api_gateway.jwt_utils import decode_internal_jwt

    token = call_kwargs["headers"]["X-Internal-JWT"]
    payload = decode_internal_jwt(token, app.state.rsa_public_key)
    assert payload["sub"] == "system:api-gateway"
    assert payload["role"] == "system"
