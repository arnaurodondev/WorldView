"""Contract tests for GET /api/v1/search/documents (PLAN-0064 W6 T-W6-1-02).

Wave 1 verified: correct 422 on bad inputs, 501 on valid input (use case not wired).
Wave 3 update: 501 assertions updated to 200 now that the use case is wired.

WHY use TestClient / ASGI transport (not full app): The full lifespan connects to DBs,
Kafka, and Valkey. These tests spin up only the bare router under a minimal FastAPI app,
so they run fast (no I/O), work in CI with no infra, and are pure unit tests.

Wave 3 approach: the router now requires `SearchDocumentsUseCaseDep` to be injected.
We override `get_search_documents_use_case` in the app's dependency_overrides to
provide a mock use case that returns a valid empty response, so the 422 tests remain
un-mocked (FastAPI validation fires before the dependency is resolved) while the
"valid request" tests get a real-ish response from the mock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_search_documents_use_case
from nlp_pipeline.api.routes.search_documents import router
from nlp_pipeline.application.use_cases.search_documents import SearchDocumentsOutput

pytestmark = pytest.mark.unit

# A valid empty SearchDocumentsOutput that the mock use case returns.
# Used by the "valid request" contract tests so the route serialises correctly.
_EMPTY_OUTPUT = SearchDocumentsOutput(
    query="apple earnings",
    total=0,
    page=1,
    page_size=25,
    has_more=False,
    results=[],
    facets=[],
    latency_ms=1,
)


def _make_app() -> FastAPI:
    """Minimal FastAPI with the search_documents router + mocked use case.

    The mock returns _EMPTY_OUTPUT for any call — sufficient for contract tests
    that only care about HTTP status codes and response shape, not data.
    """
    app = FastAPI()
    app.include_router(router)

    # Override the use case dependency so the route handler doesn't try to
    # resolve a real DB session or config from app.state (which doesn't exist
    # in this minimal app).
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=_EMPTY_OUTPUT)
    # Dependency override: any function that needs get_search_documents_use_case
    # will receive the mock_uc instead.
    app.dependency_overrides[get_search_documents_use_case] = lambda: mock_uc

    return app


# ── 422 contract tests ────────────────────────────────────────────────────────
# These fire BEFORE the dependency is resolved — FastAPI's query-param validation
# returns 422 immediately, so the mock use case is never called.


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


# ── Wave 3 contract tests — now 200 ──────────────────────────────────────────
# Updated from Wave 1 (which expected 501) — use case is now wired.


@pytest.mark.asyncio
async def test_valid_request_returns_200() -> None:
    """A valid request returns 200 now that Wave 3 has wired the use case.

    The mock use case returns an empty SearchDocumentsOutput — this tests the
    full serialisation path (route → mapper → Pydantic → JSON) without a real DB.
    """
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "apple earnings"},
        )

    assert response.status_code == 200
    body = response.json()
    # Response must include all top-level keys defined in SearchDocumentsResponse.
    assert "total" in body
    assert "results" in body
    assert "facets" in body
    assert "latency_ms" in body
    assert "has_more" in body
    assert body["query"] == "apple earnings"


@pytest.mark.asyncio
async def test_valid_request_with_entity_id_returns_200() -> None:
    """Valid request with entity_id filter returns 200 in Wave 3."""
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

    assert response.status_code == 200
