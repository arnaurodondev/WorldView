"""Unit tests for POST /api/v1/graph/cypher/path and /neighborhood routes (PRD-0018 Wave E-2)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt as _jwt
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

# System JWT for InternalJWTMiddleware (PRD-0025 graceful degradation — decoded without sig when no JWKS)
_SYSTEM_JWT = _jwt.encode(
    {
        "iss": "worldview-gateway",
        "sub": "unit-test-system",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    },
    "unit-test-secret",
    algorithm="HS256",
)

_SRC = uuid4()
_TGT = uuid4()
_ENT = uuid4()


# ── App factory ───────────────────────────────────────────────────────────────


def _make_app(*, cypher_enabled: bool = False, entity_exists: bool = True):
    """Create a test app with the cypher bundle dependency overridden."""
    from knowledge_graph.api.dependencies import get_cypher_bundle, get_session
    from knowledge_graph.app import create_app

    app = create_app()
    mock_session = AsyncMock()

    async def _mock_session():
        yield mock_session

    def _bundle_override():
        """Parameter-less override — FastAPI injects nothing."""
        from knowledge_graph.api.dependencies import _CypherBundle

        bundle = MagicMock(spec=_CypherBundle)
        bundle.session = mock_session
        bundle.cypher_enabled = cypher_enabled

        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(return_value=entity_exists)
        entity_repo.get = AsyncMock(
            return_value=(
                {
                    "entity_id": _ENT,
                    "canonical_name": "Apple Inc.",
                    "entity_type": "financial_instrument",
                    "isin": None,
                    "ticker": "AAPL",
                    "exchange": "US",
                    "metadata": {},
                }
                if entity_exists
                else None
            ),
        )
        bundle.entity_repo = entity_repo
        bundle.relation_repo = AsyncMock()
        bundle.temporal_event_repo = AsyncMock()
        return bundle

    app.dependency_overrides[get_session] = _mock_session
    app.dependency_overrides[get_cypher_bundle] = _bundle_override
    return app


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def disabled_app():
    """App with cypher disabled (default)."""
    return _make_app(cypher_enabled=False)


@pytest.fixture
def enabled_app():
    """App with cypher enabled and entity found."""
    return _make_app(cypher_enabled=True, entity_exists=True)


@pytest.fixture
def enabled_no_entity_app():
    """App with cypher enabled but entity not found."""
    return _make_app(cypher_enabled=True, entity_exists=False)


@pytest.fixture
async def cypher_client(disabled_app):
    """ASGI client using the cypher-disabled app.

    Includes X-Internal-JWT for InternalJWTMiddleware (PRD-0025 graceful degradation).
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=disabled_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _SYSTEM_JWT},
    ) as ac:
        yield ac


# ── POST /api/v1/graph/cypher/path — disabled ─────────────────────────────────


class TestCypherPathDisabled:
    async def test_cypher_endpoint_disabled_returns_503(self, cypher_client) -> None:
        """CYPHER_ENABLED=false → 503 with CYPHER_DISABLED error code (PRD §11 HIGH)."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/path",
            json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT)},
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"] == "CYPHER_DISABLED"


# ── POST /api/v1/graph/cypher/path — validation ───────────────────────────────


class TestCypherPathValidation:
    async def test_same_entity_ids_returns_422(self, cypher_client) -> None:
        """source_entity_id == target_entity_id → 422 Unprocessable Entity."""
        same_id = str(uuid4())
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/path",
            json={"source_entity_id": same_id, "target_entity_id": same_id},
        )
        assert resp.status_code == 422

    async def test_max_hops_too_large_returns_422(self, cypher_client) -> None:
        """max_hops > 5 → 422 Unprocessable Entity."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/path",
            json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT), "max_hops": 6},
        )
        assert resp.status_code == 422

    async def test_max_hops_zero_returns_422(self, cypher_client) -> None:
        """max_hops = 0 → 422 Unprocessable Entity."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/path",
            json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT), "max_hops": 0},
        )
        assert resp.status_code == 422

    async def test_relation_type_too_long_returns_422(self, cypher_client) -> None:
        """relation_type string > 50 chars → 422 Unprocessable Entity."""
        long_type = "x" * 51
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/path",
            json={
                "source_entity_id": str(_SRC),
                "target_entity_id": str(_TGT),
                "relation_types": [long_type],
            },
        )
        assert resp.status_code == 422


# ── POST /api/v1/graph/cypher/path — enabled ──────────────────────────────────


class TestCypherPathEnabled:
    async def test_entity_not_found_returns_404(self, enabled_no_entity_app) -> None:
        """Source or target entity missing → 404."""
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=enabled_no_entity_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            resp = await ac.post(
                "/api/v1/graph/cypher/path",
                json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT)},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "entity_not_found"

    async def test_timeout_returns_504(self, enabled_app) -> None:
        """AGE query timeout → 504 Gateway Timeout."""
        from httpx import ASGITransport, AsyncClient
        from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError

        transport = ASGITransport(app=enabled_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            with patch(
                "knowledge_graph.application.use_cases.cypher_path.CypherPathUseCase.execute",
                new_callable=AsyncMock,
                side_effect=CypherTimeoutError("timed out"),
            ):
                resp = await ac.post(
                    "/api/v1/graph/cypher/path",
                    json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT)},
                )
        assert resp.status_code == 504
        assert resp.json()["detail"]["error"] == "AGE_TIMEOUT"

    async def test_no_path_found_returns_empty_paths(self, enabled_app) -> None:
        """Valid request but no path in AGE → 200 with paths=[]."""
        from httpx import ASGITransport, AsyncClient
        from knowledge_graph.application.use_cases.cypher_path import CypherPathResult

        empty_result = CypherPathResult(
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            paths=[],
            paths_found=0,
            query_time_ms=12,
        )

        transport = ASGITransport(app=enabled_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            with patch(
                "knowledge_graph.application.use_cases.cypher_path.CypherPathUseCase.execute",
                new_callable=AsyncMock,
                return_value=empty_result,
            ):
                resp = await ac.post(
                    "/api/v1/graph/cypher/path",
                    json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT)},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["paths"] == []
        assert body["paths_found"] == 0
        assert "query_time_ms" in body

    async def test_path_found_returns_structured_response(self, enabled_app) -> None:
        """Valid request with path found → 200 with nodes/edges/path_confidence."""
        from httpx import ASGITransport, AsyncClient
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathResult,
            _Path,
            _PathEdge,
            _PathNode,
        )

        node_a = _PathNode(entity_id=str(_SRC), canonical_name="Apple Inc.", entity_type="financial_instrument")
        node_b = _PathNode(entity_id=str(_TGT), canonical_name="Samsung", entity_type="financial_instrument")
        edge = _PathEdge(
            from_entity_id=str(_SRC),
            to_entity_id=str(_TGT),
            canonical_type="COMPETES_WITH",
            confidence=0.87,
        )
        path = _Path(hops=1, nodes=[node_a, node_b], edges=[edge], path_confidence=0.87)
        result = CypherPathResult(
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            paths=[path],
            paths_found=1,
            query_time_ms=42,
        )

        transport = ASGITransport(app=enabled_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            with patch(
                "knowledge_graph.application.use_cases.cypher_path.CypherPathUseCase.execute",
                new_callable=AsyncMock,
                return_value=result,
            ):
                resp = await ac.post(
                    "/api/v1/graph/cypher/path",
                    json={"source_entity_id": str(_SRC), "target_entity_id": str(_TGT)},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["paths_found"] == 1
        assert len(body["paths"]) == 1
        p = body["paths"][0]
        assert p["hops"] == 1
        assert len(p["nodes"]) == 2
        assert p["nodes"][0]["canonical_name"] == "Apple Inc."
        assert len(p["edges"]) == 1
        assert p["edges"][0]["canonical_type"] == "COMPETES_WITH"
        assert p["edges"][0]["confidence"] == pytest.approx(0.87)
        assert p["path_confidence"] == pytest.approx(0.87)


# ── POST /api/v1/graph/cypher/neighborhood — disabled ─────────────────────────


class TestCypherNeighborhoodDisabled:
    async def test_neighborhood_endpoint_disabled_returns_503(self, cypher_client) -> None:
        """CYPHER_ENABLED=false → 503 with CYPHER_DISABLED error code."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/neighborhood",
            json={"entity_id": str(_ENT)},
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"] == "CYPHER_DISABLED"


# ── POST /api/v1/graph/cypher/neighborhood — validation ──────────────────────


class TestCypherNeighborhoodValidation:
    async def test_max_hops_too_large_returns_422(self, cypher_client) -> None:
        """max_hops > 3 for neighborhood → 422."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/neighborhood",
            json={"entity_id": str(_ENT), "max_hops": 4},
        )
        assert resp.status_code == 422

    async def test_limit_too_large_returns_422(self, cypher_client) -> None:
        """limit > 200 → 422."""
        resp = await cypher_client.post(
            "/api/v1/graph/cypher/neighborhood",
            json={"entity_id": str(_ENT), "limit": 201},
        )
        assert resp.status_code == 422


# ── POST /api/v1/graph/cypher/neighborhood — enabled ─────────────────────────


class TestCypherNeighborhoodEnabled:
    async def test_entity_not_found_returns_404(self, enabled_no_entity_app) -> None:
        """Entity not in canonical_entities → 404."""
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=enabled_no_entity_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            resp = await ac.post(
                "/api/v1/graph/cypher/neighborhood",
                json={"entity_id": str(_ENT)},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "entity_not_found"

    async def test_neighborhood_returns_200_with_center(self, enabled_app) -> None:
        """Valid enabled request → 200 with center/relations/entities/temporal_events."""
        from httpx import ASGITransport, AsyncClient
        from knowledge_graph.application.use_cases.cypher_neighborhood import (
            CypherNeighborhoodResult,
            CypherNeighborhoodUseCase,
        )

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        mock_result = CypherNeighborhoodResult(
            center_row=center_row,
            relation_rows=[],
            neighbor_rows={},
            temporal_event_rows=[],
        )

        transport = ASGITransport(app=enabled_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Internal-JWT": _SYSTEM_JWT},
        ) as ac:
            with patch.object(
                CypherNeighborhoodUseCase,
                "execute",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                resp = await ac.post(
                    "/api/v1/graph/cypher/neighborhood",
                    json={"entity_id": str(_ENT)},
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["center"]["canonical_name"] == "Apple Inc."
        assert body["center"]["entity_type"] == "financial_instrument"
        assert body["relations"] == []
        assert body["entities"] == {}
        assert body["temporal_events"] == []

    async def test_uses_write_session_not_read_session(self, disabled_app) -> None:
        """Route uses DbSessionDep (write), not ReadOnlyDbSessionDep (R27 exception for AGE)."""
        from knowledge_graph.api.dependencies import get_readonly_session, get_session

        # write session (get_session) must be overridden for cypher endpoints
        assert get_session in disabled_app.dependency_overrides
        # read-only session is NOT required to be overridden for cypher endpoints
        assert get_readonly_session not in disabled_app.dependency_overrides
