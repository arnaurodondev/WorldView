"""Unit tests for GET /api/v1/documents/cluster/{cluster_id}/articles endpoint (P2-F)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from content_store.api.dependencies import get_cluster_articles_use_case
from content_store.application.use_cases.get_cluster_articles import ClusterArticleDTO

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)

# Any value works for X-Internal-JWT in unit tests — middleware passes through
# without signature verification when public_key is None (skip_verification=True).
_JWT_HEADERS = {"X-Internal-JWT": "unit.test.token"}


def _make_dto(cluster_id=None, doc_id=None) -> ClusterArticleDTO:
    return ClusterArticleDTO(
        id=doc_id or uuid4(),
        title="Test Article",
        url="https://example.com/article",
        published_at=_NOW,
        source_name=None,
        cluster_id=cluster_id or uuid4(),
        cluster_size=2,
    )


def _override(mock_uc):
    def dep():
        return mock_uc

    return dep


# ── Authentication ────────────────────────────────────────────────────────────


async def test_cluster_articles_requires_x_internal_jwt(app, unauthenticated_client) -> None:
    """No X-Internal-JWT → 401 from InternalJWTMiddleware (PRD-0025)."""
    cluster_id = uuid4()
    resp = await unauthenticated_client.get(f"/api/v1/documents/cluster/{cluster_id}/articles")
    assert resp.status_code == 401


# ── 404 when cluster not found ────────────────────────────────────────────────


async def test_cluster_articles_returns_404_when_not_found(app, client) -> None:
    """Cluster_id not in DB → use case returns [] → 404."""
    cluster_id = uuid4()

    mock_uc = AsyncMock()
    mock_uc.execute.return_value = []
    app.dependency_overrides[get_cluster_articles_use_case] = _override(mock_uc)

    try:
        resp = await client.get(
            f"/api/v1/documents/cluster/{cluster_id}/articles",
            headers=_JWT_HEADERS,
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# ── Happy path ────────────────────────────────────────────────────────────────


async def test_cluster_articles_returns_two_articles(app, client) -> None:
    """Cluster with 2 articles → 200 with both in response."""
    cluster_id = uuid4()
    doc_id_1, doc_id_2 = uuid4(), uuid4()
    dto1 = _make_dto(cluster_id=cluster_id, doc_id=doc_id_1)
    dto2 = _make_dto(cluster_id=cluster_id, doc_id=doc_id_2)

    mock_uc = AsyncMock()
    mock_uc.execute.return_value = [dto1, dto2]
    app.dependency_overrides[get_cluster_articles_use_case] = _override(mock_uc)

    try:
        resp = await client.get(
            f"/api/v1/documents/cluster/{cluster_id}/articles",
            headers=_JWT_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "articles" in body
        assert len(body["articles"]) == 2
        returned_ids = {a["id"] for a in body["articles"]}
        assert str(doc_id_1) in returned_ids
        assert str(doc_id_2) in returned_ids
    finally:
        app.dependency_overrides.clear()


# ── Response shape ────────────────────────────────────────────────────────────


async def test_cluster_articles_response_fields(app, client) -> None:
    """Response article objects contain all required fields."""
    cluster_id = uuid4()
    doc_id = uuid4()
    dto = ClusterArticleDTO(
        id=doc_id,
        title="Fed Raises Rates by 25bp",
        url="https://bloomberg.com/fed-hikes",
        published_at=_NOW,
        source_name=None,
        cluster_id=cluster_id,
        cluster_size=2,
    )
    mock_uc = AsyncMock()
    mock_uc.execute.return_value = [dto]
    app.dependency_overrides[get_cluster_articles_use_case] = _override(mock_uc)

    try:
        resp = await client.get(
            f"/api/v1/documents/cluster/{cluster_id}/articles",
            headers=_JWT_HEADERS,
        )
        assert resp.status_code == 200
        article = resp.json()["articles"][0]
        assert article["id"] == str(doc_id)
        assert article["title"] == "Fed Raises Rates by 25bp"
        assert article["url"] == "https://bloomberg.com/fed-hikes"
        assert article["source_name"] is None
        assert article["cluster_id"] == str(cluster_id)
        assert article["cluster_size"] == 2
    finally:
        app.dependency_overrides.clear()


# ── Invalid UUID ──────────────────────────────────────────────────────────────


async def test_cluster_articles_invalid_uuid_returns_422(app, client) -> None:
    """Non-UUID cluster_id → FastAPI path parameter validation → 422."""
    resp = await client.get(
        "/api/v1/documents/cluster/not-a-uuid/articles",
        headers=_JWT_HEADERS,
    )
    assert resp.status_code == 422
