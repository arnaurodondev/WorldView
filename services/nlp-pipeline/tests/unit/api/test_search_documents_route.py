"""Route handler tests for GET /api/v1/search/documents (PLAN-0064 W6 T-W6-3-01).

Tests the Wave 3 route handler: use case injection, response mapping, error handling,
and Prometheus metrics. All tests use a minimal FastAPI app with a mocked use case —
no DB, no Kafka, no Valkey (pure unit tests).

WHY this file exists alongside test_search_documents_contract.py:
  - Contract tests (T-W6-1-02) focus on input validation (422 paths) and basic 200.
  - Route tests (T-W6-3-01) focus on the handler logic: error mapping, metrics wiring,
    facet serialisation, repeated query params, and the success/error status labels.

Architecture note: Prometheus metrics are imported inside the route handler body
(not at module level) per R25 — the architecture test will flag module-level imports
from infrastructure/* in api/routes/*. Metrics are shared global state, so tests can
read .labels(...).get() after calling the endpoint to verify instrumentation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_search_documents_use_case
from nlp_pipeline.api.routes.search_documents import router
from nlp_pipeline.application.use_cases.search_documents import (
    FatalSearchError,
    RetryableSearchError,
    SearchDocumentsFacetResult,
    SearchDocumentsHit,
    SearchDocumentsOutput,
)

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_DOC_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000001")
_DOC_ID_2 = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")
_ENTITY_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")
_ENTITY_ID_2 = uuid.UUID("018f1e2a-0000-7000-8000-000000000011")


def _make_hit(doc_id: uuid.UUID = _DOC_ID_1, score: float = 0.75) -> SearchDocumentsHit:
    """Build a minimal SearchDocumentsHit for testing."""
    return SearchDocumentsHit(
        doc_id=doc_id,
        title="Apple Q3 Earnings Beat",
        source_type="news",
        source_url="https://example.com/apple-earnings",
        published_at=datetime(2025, 7, 1, 12, 0, 0, tzinfo=UTC),
        snippet="Apple announced record revenue this quarter.",
        match_offsets=[(0, 5)],
        score=score,
        entity_hits=[_ENTITY_ID_1],
    )


def _make_facet(entity_id: uuid.UUID = _ENTITY_ID_1, count: int = 3) -> SearchDocumentsFacetResult:
    """Build a minimal SearchDocumentsFacetResult for testing."""
    return SearchDocumentsFacetResult(
        entity_id=entity_id,
        name="Apple Inc.",
        entity_type="organization",
        count=count,
    )


def _make_output(
    hits: list[SearchDocumentsHit] | None = None,
    facets: list[SearchDocumentsFacetResult] | None = None,
    total: int | None = None,
) -> SearchDocumentsOutput:
    """Build a SearchDocumentsOutput for testing."""
    resolved_hits = hits if hits is not None else [_make_hit()]
    return SearchDocumentsOutput(
        query="apple",
        total=total if total is not None else len(resolved_hits),
        page=1,
        page_size=25,
        has_more=False,
        results=resolved_hits,
        facets=facets if facets is not None else [_make_facet()],
        latency_ms=42,
    )


def _make_app(use_case_mock: AsyncMock) -> FastAPI:
    """Minimal FastAPI with only the search_documents router + mocked use case."""
    app = FastAPI()
    app.include_router(router)
    # Replace the real dependency with the mock — no DB/config resolution needed.
    app.dependency_overrides[get_search_documents_use_case] = lambda: use_case_mock
    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_search_documents_200_with_results() -> None:
    """Valid request with mocked use case returns 200 with correct response shape.

    Verifies that the route correctly maps SearchDocumentsOutput → SearchDocumentsResponse
    and that the JSON body contains all expected keys with correct values.
    """
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=_make_output())

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents", params={"q": "apple"})

    assert response.status_code == 200
    body = response.json()

    # Top-level response structure matches SearchDocumentsResponse schema.
    assert body["query"] == "apple"
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert body["has_more"] is False
    assert body["latency_ms"] == 42
    assert len(body["results"]) == 1
    assert len(body["facets"]) == 1

    # Result fields
    result = body["results"][0]
    assert result["doc_id"] == str(_DOC_ID_1)
    assert result["title"] == "Apple Q3 Earnings Beat"
    assert result["source_type"] == "news"
    assert result["score"] == pytest.approx(0.75)
    assert result["snippet"] == "Apple announced record revenue this quarter."
    assert result["match_offsets"] == [[0, 5]]

    # Facet fields
    facet = body["facets"][0]
    assert facet["entity_id"] == str(_ENTITY_ID_1)
    assert facet["name"] == "Apple Inc."
    assert facet["entity_type"] == "organization"
    assert facet["count"] == 3


@pytest.mark.asyncio
async def test_get_search_documents_503_on_retryable() -> None:
    """RetryableSearchError from use case maps to HTTP 503.

    The route must catch RetryableSearchError and return 503 so clients know
    the failure is transient and retrying may succeed.
    """
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(side_effect=RetryableSearchError("DB timeout"))

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents", params={"q": "apple"})

    assert response.status_code == 503
    body = response.json()
    # Body must have a `detail` key — never empty (BP-064).
    assert "detail" in body
    assert "retry" in body["detail"].lower()


@pytest.mark.asyncio
async def test_get_search_documents_500_on_fatal() -> None:
    """FatalSearchError from use case maps to HTTP 500.

    The route must catch FatalSearchError and return 500 with a generic error
    message — the real error is logged (not leaked to the client).
    """
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(side_effect=FatalSearchError("schema mismatch"))

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents", params={"q": "apple"})

    assert response.status_code == 500
    body = response.json()
    assert "detail" in body


@pytest.mark.asyncio
async def test_get_search_documents_metrics_incremented_on_ok() -> None:
    """Successful request increments s6_search_documents_total with status=ok.

    Prometheus counters are shared global state — we read the counter value
    after the request and check that it increased by exactly 1 with the expected
    label combination.
    """
    from nlp_pipeline.infrastructure.metrics.prometheus import s6_search_documents_total

    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=_make_output())

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)

    # Read the counter value before the request.
    before = s6_search_documents_total.labels(source_type="news", status="ok")._value.get()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "apple", "source_type": "news"},
        )

    assert response.status_code == 200
    after = s6_search_documents_total.labels(source_type="news", status="ok")._value.get()
    # Counter must have incremented by exactly 1.
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_get_search_documents_metrics_incremented_on_error() -> None:
    """RetryableSearchError increments s6_search_documents_total with status=error.

    The `finally` block in the route handler must label the counter correctly
    for all exit paths, including exceptions.
    """
    from nlp_pipeline.infrastructure.metrics.prometheus import s6_search_documents_total

    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(side_effect=RetryableSearchError("timeout"))

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)

    # Use "all" source_type (the default) for the label check.
    before = s6_search_documents_total.labels(source_type="all", status="error")._value.get()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents", params={"q": "apple"})

    assert response.status_code == 503
    after = s6_search_documents_total.labels(source_type="all", status="error")._value.get()
    assert after == before + 1.0


@pytest.mark.asyncio
async def test_get_search_documents_repeating_entity_id_params() -> None:
    """?entity_id=uuid1&entity_id=uuid2 is parsed as a list of 2 UUIDs.

    FastAPI natively parses repeated query params with the same key into a list
    when the route declares `entity_id: list[UUID] | None = Query(None)`.
    This test confirms both UUIDs reach the use case.
    """
    mock_uc = AsyncMock()
    # Return an empty output — we only care that execute() was called with both UUIDs.
    mock_uc.execute = AsyncMock(
        return_value=SearchDocumentsOutput(
            query="apple",
            total=0,
            page=1,
            page_size=25,
            has_more=False,
            results=[],
            facets=[],
            latency_ms=1,
        )
    )

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params=[
                ("q", "apple"),
                ("entity_id", str(_ENTITY_ID_1)),
                ("entity_id", str(_ENTITY_ID_2)),
            ],
        )

    assert response.status_code == 200
    mock_uc.execute.assert_called_once()
    call_req = mock_uc.execute.call_args[0][0]
    # Both entity_ids must appear in the request.
    assert len(call_req.entity_ids) == 2
    assert _ENTITY_ID_1 in call_req.entity_ids
    assert _ENTITY_ID_2 in call_req.entity_ids


@pytest.mark.asyncio
async def test_get_search_documents_returns_facets() -> None:
    """Response includes facets list from the use case output.

    Facets are entity aggregations (name, type, mention count). The route must
    correctly map SearchDocumentsFacetResult domain objects → SearchDocumentsFacet
    Pydantic schema and include them in the response body.
    """
    facets = [
        _make_facet(entity_id=_ENTITY_ID_1, count=5),
        _make_facet(entity_id=_ENTITY_ID_2, count=2),
    ]
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=_make_output(facets=facets, total=2))

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/documents", params={"q": "apple"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["facets"]) == 2
    # Facets should be ordered by count descending (repo returns top-25 by count).
    assert body["facets"][0]["entity_id"] == str(_ENTITY_ID_1)
    assert body["facets"][0]["count"] == 5
    assert body["facets"][1]["entity_id"] == str(_ENTITY_ID_2)
    assert body["facets"][1]["count"] == 2


@pytest.mark.asyncio
async def test_get_search_documents_empty_result_status_label() -> None:
    """A valid request with zero results increments counter with status=empty.

    "empty" is a third status label distinct from "ok" and "error" — it signals
    that the query executed successfully but returned no matching documents.
    """
    from nlp_pipeline.infrastructure.metrics.prometheus import s6_search_documents_total

    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(
        return_value=SearchDocumentsOutput(
            query="xyzzy42nonexistent",
            total=0,
            page=1,
            page_size=25,
            has_more=False,
            results=[],
            facets=[],
            latency_ms=5,
        )
    )

    app = _make_app(mock_uc)
    transport = ASGITransport(app=app)

    before = s6_search_documents_total.labels(source_type="all", status="empty")._value.get()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/search/documents",
            params={"q": "xyzzy42nonexistent"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0

    after = s6_search_documents_total.labels(source_type="all", status="empty")._value.get()
    # Counter must have incremented by exactly 1 for the "empty" status.
    assert after == before + 1.0
