"""Unit tests for POST /api/v1/documents/batch endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from content_store.api.dependencies import get_batch_documents_use_case
from content_store.application.ports.repositories import DocumentMetadataDTO

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)


def _make_dto(doc_id=None) -> DocumentMetadataDTO:
    return DocumentMetadataDTO(
        doc_id=doc_id or uuid4(),
        title="Test Article",
        url="https://example.com/article",
        published_at=_NOW,
        source_name=None,
        source_type="news",
        word_count=800,
    )


def _override(mock_uc):
    def dep():
        return mock_uc

    return dep


# ── Happy path ────────────────────────────────────────────────────────────────


async def test_batch_documents_endpoint_found(app, client) -> None:
    """2 existing doc_ids → 200 with 2 documents."""
    id1, id2 = uuid4(), uuid4()
    dto1, dto2 = _make_dto(id1), _make_dto(id2)

    mock_uc = AsyncMock()
    mock_uc.execute.return_value = [dto1, dto2]
    app.dependency_overrides[get_batch_documents_use_case] = _override(mock_uc)

    try:
        resp = await client.post("/api/v1/documents/batch", json={"doc_ids": [str(id1), str(id2)]})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["documents"]) == 2
        doc_ids_returned = {d["doc_id"] for d in body["documents"]}
        assert str(id1) in doc_ids_returned
        assert str(id2) in doc_ids_returned
    finally:
        app.dependency_overrides.clear()


async def test_batch_documents_endpoint_partial_match(app, client) -> None:
    """3 ids, only 1 found in DB → 200 with 1 document."""
    id1, id2, id3 = uuid4(), uuid4(), uuid4()
    dto = _make_dto(id1)

    mock_uc = AsyncMock()
    mock_uc.execute.return_value = [dto]
    app.dependency_overrides[get_batch_documents_use_case] = _override(mock_uc)

    try:
        resp = await client.post(
            "/api/v1/documents/batch",
            json={"doc_ids": [str(id1), str(id2), str(id3)]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["documents"]) == 1
    finally:
        app.dependency_overrides.clear()


async def test_batch_documents_endpoint_no_match(app, client) -> None:
    """No doc_ids match DB → 200 with empty list."""
    mock_uc = AsyncMock()
    mock_uc.execute.return_value = []
    app.dependency_overrides[get_batch_documents_use_case] = _override(mock_uc)

    try:
        resp = await client.post("/api/v1/documents/batch", json={"doc_ids": [str(uuid4())]})
        assert resp.status_code == 200
        assert resp.json()["documents"] == []
    finally:
        app.dependency_overrides.clear()


# ── Error paths ───────────────────────────────────────────────────────────────


async def test_batch_documents_endpoint_too_many(app, client) -> None:
    """51 doc_ids → use case raises DomainError → 400."""
    from content_store.domain.errors import DomainError

    mock_uc = AsyncMock()
    mock_uc.execute.side_effect = DomainError("Too many doc_ids: max 50, got 51")
    app.dependency_overrides[get_batch_documents_use_case] = _override(mock_uc)

    try:
        resp = await client.post(
            "/api/v1/documents/batch",
            json={"doc_ids": [str(uuid4()) for _ in range(51)]},
        )
        assert resp.status_code == 400
        assert "Too many doc_ids" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


async def test_batch_documents_endpoint_empty_list_rejected(app, client) -> None:
    """Empty doc_ids list → Pydantic validation error → 422."""
    resp = await client.post("/api/v1/documents/batch", json={"doc_ids": []})
    assert resp.status_code == 422


async def test_batch_documents_endpoint_invalid_uuid(app, client) -> None:
    """Non-UUID value in doc_ids → 422."""
    resp = await client.post("/api/v1/documents/batch", json={"doc_ids": ["not-a-uuid"]})
    assert resp.status_code == 422


# ── Response shape ────────────────────────────────────────────────────────────


async def test_batch_documents_response_fields(app, client) -> None:
    """Response document objects contain all required fields."""
    doc_id = uuid4()
    dto = DocumentMetadataDTO(
        doc_id=doc_id,
        title="SEC 10-K Filing",
        url="https://sec.gov/10k",
        published_at=_NOW,
        source_name=None,
        source_type="sec_10k",
        word_count=25000,
    )
    mock_uc = AsyncMock()
    mock_uc.execute.return_value = [dto]
    app.dependency_overrides[get_batch_documents_use_case] = _override(mock_uc)

    try:
        resp = await client.post("/api/v1/documents/batch", json={"doc_ids": [str(doc_id)]})
        assert resp.status_code == 200
        doc = resp.json()["documents"][0]
        assert doc["doc_id"] == str(doc_id)
        assert doc["title"] == "SEC 10-K Filing"
        assert doc["url"] == "https://sec.gov/10k"
        assert doc["source_name"] is None
        assert doc["source_type"] == "sec_10k"
        assert doc["word_count"] == 25000
    finally:
        app.dependency_overrides.clear()
