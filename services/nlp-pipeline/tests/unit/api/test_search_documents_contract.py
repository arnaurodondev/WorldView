"""Contract tests for GET /api/v1/search/documents (PLAN-0064 W6 T-W6-1-02).

Wave 1 verifies: correct 422 on bad inputs, 501 on valid input (use case not yet wired).

WHY use TestClient / ASGI transport (not full app): The full lifespan connects to DBs,
Kafka, and Valkey. These tests spin up only the bare router under a minimal FastAPI app,
so they run fast (no I/O), work in CI with no infra, and are pure unit tests.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.routes.search_documents import router

pytestmark = pytest.mark.unit


def _make_app() -> FastAPI:
    """Minimal FastAPI with only the search_documents router — no DB, no Kafka."""
    app = FastAPI()
    app.include_router(router)
    return app


# ── 422 contract tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_q_returns_422() -> None:
    """GET /api/v1/search/documents with no q param must return 422."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_uuid_entity_id_returns_422() -> None:
    """entity_id that is not a valid UUID must return 422."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "apple", "entity_id": "not-a-uuid"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_page_zero_returns_422() -> None:
    """page=0 is below the ge=1 constraint and must return 422."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "apple", "page": "0"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_q_over_500_chars_returns_422() -> None:
    """q longer than 500 chars must return 422 from FastAPI query validation."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "a" * 501},
        )

    assert response.status_code == 422


# ── 501 stub contract test ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_request_returns_501_for_now() -> None:
    """A valid request returns 501 (Wave 3 wires the use case).

    This is the Wave 1 contract: the route exists, validates params, and returns
    501 so frontend teams can code against the contract without waiting for Wave 3.
    """
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "apple earnings"},
        )

    assert response.status_code == 501
    body = response.json()
    assert "detail" in body
    assert body["detail"] == "not yet implemented"


@pytest.mark.asyncio
async def test_valid_request_with_entity_id_returns_501() -> None:
    """Valid request with entity_id filter also returns 501 in Wave 1."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={
                "q": "revenue miss",
                "entity_id": "018f1e2a-0000-7000-8000-000000000001",
                "source_type": "sec_edgar",
                "page": "2",
                "page_size": "50",
            },
        )

    assert response.status_code == 501
