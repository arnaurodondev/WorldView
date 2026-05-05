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
):
    """Build a test app with GetEntityGraphUseCase patched to avoid real repos."""
    from knowledge_graph.api.dependencies import get_entity_graph_repos
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

    app.dependency_overrides[get_entity_graph_repos] = _repos_override

    # Patch the use case at class level so it returns our fixtures regardless of repos
    import knowledge_graph.api.routes as _routes_mod

    async def _fake_execute(**kwargs):
        return entity_row, relation_rows or [], entities_map or {}

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
