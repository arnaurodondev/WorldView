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

    Also overrides get_cypher_bundle and get_cypher_neighborhood_uc (DEF-015:
    CypherNeighborhoodUseCase is now injected via Depends rather than called inline).
    By default cypher_enabled=False so existing depth=1 tests are unaffected.
    """
    from knowledge_graph.api.dependencies import get_cypher_bundle, get_cypher_neighborhood_uc, get_entity_graph_repos
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

    def _cypher_uc_override():
        # Return a simple mock; tests that exercise the cypher path patch the execute
        # method directly (see test_depth_2_delegates_to_cypher_use_case).
        from unittest.mock import AsyncMock as _AsyncMock

        uc = MagicMock()
        uc.execute = _AsyncMock(return_value=None)
        return uc

    app.dependency_overrides[get_entity_graph_repos] = _repos_override
    app.dependency_overrides[get_cypher_bundle] = _cypher_override
    # Override the DI-injected CypherNeighborhoodUseCase (DEF-015 fix).
    app.dependency_overrides[get_cypher_neighborhood_uc] = _cypher_uc_override

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

    async def test_evidence_snippets_respects_limit_param(self) -> None:
        """evidence_snippets_limit=2 is forwarded as evidence_limit=2 to GetEntityGraphUseCase.execute().

        The route converts the query param name (evidence_snippets_limit) to the
        use case kwarg name (evidence_limit).  This test verifies that forwarding
        so that changing the default in the route layer does not silently break the
        contract.
        """
        from unittest.mock import patch

        from httpx import ASGITransport, AsyncClient

        # We need to intercept the call args passed to GetEntityGraphUseCase.execute,
        # so we build the app normally and then patch GetEntityGraphUseCase at the
        # routes module level with a spy class that records kwargs.
        captured_kwargs: dict = {}

        app = _make_app(entity_row=_entity_row(), relation_rows=[_relation_row()])

        import knowledge_graph.api.routes as _routes_mod

        # Build the spy after _make_app already replaced the class with _FakeUseCase.
        # We need to intercept the REAL execute path so patch at the routes module.
        class _SpyUseCase:
            async def execute(self, **kwargs):  # type: ignore[override]
                captured_kwargs.update(kwargs)
                return _entity_row(), [_relation_row()], {}

        with patch.object(_routes_mod, "GetEntityGraphUseCase", _SpyUseCase):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_HEADERS,
            ) as client:
                resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph?evidence_snippets_limit=2")

        assert resp.status_code == 200
        # Route must forward evidence_snippets_limit as the evidence_limit kwarg
        assert captured_kwargs.get("evidence_limit") == 2, (
            f"Expected evidence_limit=2, got {captured_kwargs.get('evidence_limit')!r}. "
            "Check that get_entity_graph passes evidence_limit=evidence_snippets_limit."
        )

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
        """depth=2 + cypher_enabled=True → CypherNeighborhoodUseCase called, 200 returned.

        DEF-015: CypherNeighborhoodUseCase is now DI-injected via Depends().  We
        override get_cypher_neighborhood_uc in the test app to return a mock whose
        execute() yields fake_result, rather than patching the class method directly.
        """
        from datetime import datetime

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
                },
            },
        )

        # Build app with cypher_enabled=True; _make_app already overrides
        # get_cypher_neighborhood_uc with a generic MagicMock — we replace it with
        # a mock whose execute() returns fake_result so the route can map the result.
        from knowledge_graph.api.dependencies import get_cypher_neighborhood_uc

        app = _make_app(entity_row=_entity_row(), cypher_enabled=True)

        async def _fake_execute(*args, **kwargs):
            return fake_result

        def _fake_uc_override():
            uc = MagicMock()
            uc.execute = AsyncMock(side_effect=_fake_execute)
            return uc

        app.dependency_overrides[get_cypher_neighborhood_uc] = _fake_uc_override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
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
                },
            ],
            neighbor_rows={
                str(neighbor_id): {
                    "entity_id": neighbor_id,
                    "canonical_name": "Rivian Automotive",
                    "entity_type": "company",
                    "isin": None,
                    "ticker": "RIVN",
                    "exchange": "NASDAQ",
                },
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


class TestEntitySummaryDescriptionAndSector:
    """F-101: EntitySummary must forward description and sector from entity rows."""

    async def test_center_description_populated_when_entity_row_has_description(self) -> None:
        """center node description is non-null when entity_row includes description."""
        from httpx import ASGITransport, AsyncClient

        entity_row_with_desc = {
            "entity_id": _ENTITY_ID,
            "canonical_name": "Apple Inc.",
            "entity_type": "company",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            # F-101: description comes from canonical_entities.description column
            "description": "Apple Inc. designs, manufactures, and markets consumer electronics.",
            "sector": "Technology",
        }
        app = _make_app(entity_row=entity_row_with_desc, relation_rows=[])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        center = resp.json()["center"]
        assert center["description"] == "Apple Inc. designs, manufactures, and markets consumer electronics."
        assert center["sector"] == "Technology"

    async def test_center_description_null_when_absent_from_entity_row(self) -> None:
        """center node description is null when entity_row has no description key."""
        from httpx import ASGITransport, AsyncClient

        # Row without description/sector — simulates old-style rows that pre-date F-101
        app = _make_app(entity_row=_entity_row(), relation_rows=[])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        center = resp.json()["center"]
        assert center["description"] is None
        assert center["sector"] is None

    async def test_neighbor_description_populated_via_entities_map(self) -> None:
        """Neighbor nodes carry description/sector when entity batch row includes them."""
        from httpx import ASGITransport, AsyncClient

        neighbor_id = _OBJ_ID
        neighbor_row = {
            "entity_id": neighbor_id,
            "canonical_name": "Microsoft Corp.",
            "entity_type": "company",
            "isin": None,
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "description": "Microsoft Corporation develops software and cloud services.",
            "sector": "Technology",
        }
        app = _make_app(
            entity_row=_entity_row(),
            relation_rows=[_relation_row()],
            entities_map={str(neighbor_id): neighbor_row},
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/graph")

        assert resp.status_code == 200
        entities = resp.json()["entities"]
        assert str(neighbor_id) in entities
        neighbor = entities[str(neighbor_id)]
        assert neighbor["description"] == "Microsoft Corporation develops software and cloud services."
        assert neighbor["sector"] == "Technology"
