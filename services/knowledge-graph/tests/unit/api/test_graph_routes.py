"""Unit tests for GET /api/v1/entities/{entity_id}/graph — evidence_snippets + relation_summary."""

from __future__ import annotations

import time
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt as _jwt
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ENTITY_ID = uuid4()
_OBJ_ID = uuid4()
_REL_ID = uuid4()

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
_HEADERS = {"X-Internal-JWT": _SYSTEM_JWT}


def _entity_row(entity_id=None):
    return {
        "entity_id": entity_id or _ENTITY_ID,
        "canonical_name": "Apple Inc.",
        "entity_type": "company",
        "isin": None,
        "ticker": "AAPL",
        "exchange": "NASDAQ",
    }


def _relation_row(rel_id=None, snippets=None, summary=None):
    """Row dict as returned by the use case (already merged with snippets/summary)."""
    from datetime import datetime

    now = datetime.now(tz=UTC)
    return {
        "relation_id": rel_id or _REL_ID,
        "subject_entity_id": _ENTITY_ID,
        "object_entity_id": _OBJ_ID,
        "canonical_type": "competes_with",
        "semantic_mode": "RELATION_STATE",
        "decay_class": "DURABLE",
        "confidence": 0.85,
        "confidence_stale": False,
        "evidence_count": 3,
        "first_evidence_at": now,
        "latest_evidence_at": now,
        "evidence_snippets": snippets if snippets is not None else [],
        "relation_summary": summary,
    }


def _make_app(
    *,
    entity_row=None,
    relation_rows=None,
    entities_map=None,
    cypher_enabled: bool = False,
):
    """Build a test app with GetEntityGraphUseCase patched to avoid real repos.

    Also overrides get_cypher_bundle (needed since T-72-3-01 added CypherBundleDep
    to get_entity_graph). By default cypher_enabled=False so existing depth=1
    tests are unaffected.
    """
    from knowledge_graph.api.dependencies import get_cypher_bundle, get_entity_graph_repos
    from knowledge_graph.app import create_app
    from knowledge_graph.config import Settings

    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]

    def _repos_override():
        bundle = MagicMock()
        bundle.entity_repo = AsyncMock()
        bundle.relation_repo = AsyncMock()
        bundle.evidence_repo = AsyncMock()
        bundle.summary_repo = AsyncMock()
        return bundle

    def _cypher_override():
        bundle = MagicMock()
        bundle.cypher_enabled = cypher_enabled
        bundle.session = AsyncMock()
        bundle.entity_repo = AsyncMock()
        bundle.relation_repo = AsyncMock()
        bundle.temporal_event_repo = AsyncMock()
        return bundle

    app.dependency_overrides[get_entity_graph_repos] = _repos_override
    app.dependency_overrides[get_cypher_bundle] = _cypher_override

    # Patch the use case at class level so it returns our fixtures regardless of repos
    import knowledge_graph.api.routes as _routes_mod

    original_cls = _routes_mod.GetEntityGraphUseCase

    class _FakeUseCase:
        async def execute(self, **kwargs):
            return entity_row, relation_rows or [], entities_map or {}

    _routes_mod.GetEntityGraphUseCase = _FakeUseCase  # type: ignore[misc]
    app._fake_uc_original = original_cls  # stash for teardown (unused in unit tests)

    return app


class TestGraphRouteEvidenceSnippets:
    async def test_graph_response_includes_evidence_snippets(self) -> None:
        """Relations with evidence return evidence_snippets list in API response."""
        from httpx import ASGITransport, AsyncClient

        snippets = ["Apple beat Q3 estimates.", "iPhone sales grew 12%."]
        rows = [_relation_row(snippets=snippets)]
        app = _make_app(entity_row=_entity_row(), relation_rows=rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["relations"]) == 1
        assert data["relations"][0]["evidence_snippets"] == snippets

    async def test_graph_response_empty_snippets_when_no_evidence(self) -> None:
        """Relations without evidence return evidence_snippets=[] not null."""
        from httpx import ASGITransport, AsyncClient

        rows = [_relation_row(snippets=[])]
        app = _make_app(entity_row=_entity_row(), relation_rows=rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        rel = resp.json()["relations"][0]
        assert rel["evidence_snippets"] == []
        assert rel["evidence_snippets"] is not None

    async def test_evidence_snippets_limit_max_10_rejected(self) -> None:
        """evidence_snippets_limit=11 → 422 Unprocessable Entity."""
        from httpx import ASGITransport, AsyncClient

        app = _make_app(entity_row=_entity_row(), relation_rows=[])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?evidence_snippets_limit=11")

        assert resp.status_code == 422

    async def test_evidence_snippets_default_limit_accepted(self) -> None:
        """No evidence_snippets_limit param → defaults accepted, 200 returned."""
        from httpx import ASGITransport, AsyncClient

        app = _make_app(entity_row=_entity_row(), relation_rows=[_relation_row()])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200

    async def test_graph_response_includes_relation_summary(self) -> None:
        """Relations with a current summary expose relation_summary in API response."""
        from httpx import ASGITransport, AsyncClient

        summary_text = "Apple competes with Microsoft in cloud services."
        rows = [_relation_row(summary=summary_text)]
        app = _make_app(entity_row=_entity_row(), relation_rows=rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        rel = resp.json()["relations"][0]
        assert rel["relation_summary"] == summary_text

    async def test_graph_response_relation_summary_null_when_absent(self) -> None:
        """relation_summary=null is valid when no current summary exists."""
        from httpx import ASGITransport, AsyncClient

        rows = [_relation_row(summary=None)]
        app = _make_app(entity_row=_entity_row(), relation_rows=rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        rel = resp.json()["relations"][0]
        assert rel["relation_summary"] is None

    async def test_entity_not_found_returns_404(self) -> None:
        """entity_row=None → 404 Not Found."""
        from httpx import ASGITransport, AsyncClient

        app = _make_app(entity_row=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 404


class TestGraphRouteDepthParameter:
    async def test_depth_1_uses_relational_path(self) -> None:
        """depth=1 → GetEntityGraphUseCase used; response is 200 with relations."""
        from httpx import ASGITransport, AsyncClient

        rows = [_relation_row(snippets=["Evidence text."])]
        app = _make_app(entity_row=_entity_row(), relation_rows=rows)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?depth=1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["center"]["entity_id"] == str(_ENTITY_ID)
        assert len(data["relations"]) == 1
        assert data["relations"][0]["evidence_snippets"] == ["Evidence text."]

    async def test_depth_limit_caps_at_3(self) -> None:
        """depth=4 → 422 Unprocessable Entity (le=3 constraint)."""
        from httpx import ASGITransport, AsyncClient

        app = _make_app(entity_row=_entity_row(), relation_rows=[])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?depth=4")

        assert resp.status_code == 422

    async def test_cypher_disabled_falls_back_to_depth1(self) -> None:
        """CYPHER_ENABLED=false + depth=2 → depth=1 relational path, 200 returned."""
        from httpx import ASGITransport, AsyncClient

        rows = [_relation_row()]
        # cypher_enabled=False (default) — cypher path must NOT be taken
        app = _make_app(entity_row=_entity_row(), relation_rows=rows, cypher_enabled=False)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?depth=2")

        assert resp.status_code == 200
        data = resp.json()
        assert data["center"]["entity_id"] == str(_ENTITY_ID)

    async def test_depth_2_delegates_to_cypher_use_case(self) -> None:
        """depth=2 + cypher_enabled=True → CypherNeighborhoodUseCase called, 200 returned."""
        from datetime import datetime
        from unittest.mock import patch

        from httpx import ASGITransport, AsyncClient

        cypher_neighbor_id = uuid4()
        now = datetime.now(tz=UTC)

        rel_row = {
            "relation_id": _REL_ID,
            "subject_entity_id": _ENTITY_ID,
            "object_entity_id": _OBJ_ID,
            "canonical_type": "competes_with",
            "semantic_mode": "RELATION_STATE",
            "decay_class": "DURABLE",
            "confidence": 0.75,
            "confidence_stale": False,
            "evidence_count": 2,
            "first_evidence_at": now,
            "latest_evidence_at": now,
        }
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodResult

        fake_result = CypherNeighborhoodResult(
            center_row={
                "entity_id": _ENTITY_ID,
                "canonical_name": "Apple Inc.",
                "entity_type": "company",
                "isin": None,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
            },
            relation_rows=[rel_row],
            neighbor_rows={
                str(cypher_neighbor_id): {
                    "entity_id": cypher_neighbor_id,
                    "canonical_name": "Microsoft Corp.",
                    "entity_type": "company",
                    "isin": None,
                    "ticker": "MSFT",
                    "exchange": "NASDAQ",
                }
            },
        )

        app = _make_app(entity_row=_entity_row(), cypher_enabled=True)

        async def _fake_cypher_execute(self, *args, **kwargs):
            return fake_result

        with patch(
            "knowledge_graph.application.use_cases.cypher_neighborhood.CypherNeighborhoodUseCase.execute",
            new=_fake_cypher_execute,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?depth=2")

        assert resp.status_code == 200
        data = resp.json()
        assert data["center"]["ticker"] == "AAPL"
        assert len(data["relations"]) == 1
        assert data["relations"][0]["canonical_type"] == "competes_with"
        # depth>1 path: evidence_snippets=[], relation_summary=null (not fetched on multi-hop)
        assert data["relations"][0]["evidence_snippets"] == []
        assert data["relations"][0]["relation_summary"] is None
        assert str(cypher_neighbor_id) in data["entities"]

    async def test_map_cypher_to_graph_response_shape(self) -> None:
        """_map_cypher_to_graph_response() produces a valid GraphNeighborhoodResponse."""
        from datetime import datetime

        from knowledge_graph.api.routes import _map_cypher_to_graph_response
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodResult

        neighbor_id = uuid4()
        rel_id = uuid4()
        now = datetime.now(tz=UTC)

        result = CypherNeighborhoodResult(
            center_row={
                "entity_id": _ENTITY_ID,
                "canonical_name": "Tesla Inc.",
                "entity_type": "company",
                "isin": None,
                "ticker": "TSLA",
                "exchange": "NASDAQ",
            },
            relation_rows=[
                {
                    "relation_id": rel_id,
                    "subject_entity_id": _ENTITY_ID,
                    "object_entity_id": neighbor_id,
                    "canonical_type": "competes_with",
                    "semantic_mode": "RELATION_STATE",
                    "decay_class": "DURABLE",
                    "confidence": 0.6,
                    "confidence_stale": False,
                    "evidence_count": 1,
                    "first_evidence_at": now,
                    "latest_evidence_at": now,
                }
            ],
            neighbor_rows={
                str(neighbor_id): {
                    "entity_id": neighbor_id,
                    "canonical_name": "Rivian Automotive",
                    "entity_type": "company",
                    "isin": None,
                    "ticker": "RIVN",
                    "exchange": "NASDAQ",
                }
            },
        )

        response = _map_cypher_to_graph_response(result)

        assert response.center.canonical_name == "Tesla Inc."
        assert len(response.relations) == 1
        assert response.relations[0].canonical_type == "competes_with"
        assert response.relations[0].evidence_snippets == []
        assert response.relations[0].relation_summary is None
        assert str(neighbor_id) in response.entities
        assert response.entities[str(neighbor_id)].ticker == "RIVN"
