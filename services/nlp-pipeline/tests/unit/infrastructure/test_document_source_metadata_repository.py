"""Unit tests for SQLAlchemyDocumentSourceMetadataRepository (T-B-1-03)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.domain.models import DocumentSourceMetadata
from nlp_pipeline.infrastructure.nlp_db.repositories.document_source_metadata import (
    SQLAlchemyDocumentSourceMetadataRepository,
)

pytestmark = pytest.mark.unit


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_metadata(doc_id: uuid.UUID | None = None) -> DocumentSourceMetadata:
    return DocumentSourceMetadata(
        doc_id=doc_id or uuid.uuid4(),
        title="Test Article",
        url="https://example.com",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_name="Finnhub",
        source_type="eodhd_news",
        word_count=1200,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


@pytest.mark.unit
class TestUpsertIdempotent:
    @pytest.mark.asyncio
    async def test_upsert_calls_execute(self) -> None:
        """upsert() must call session.execute() with the INSERT statement."""
        session = _make_session()
        repo = SQLAlchemyDocumentSourceMetadataRepository(session)

        await repo.upsert(_make_metadata())

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_same_doc_id_twice_no_error(self) -> None:
        """Second upsert with same doc_id must not raise (ON CONFLICT DO NOTHING)."""
        doc_id = uuid.uuid4()
        session = _make_session()
        repo = SQLAlchemyDocumentSourceMetadataRepository(session)

        await repo.upsert(_make_metadata(doc_id=doc_id))
        await repo.upsert(_make_metadata(doc_id=doc_id))

        assert session.execute.await_count == 2


@pytest.mark.unit
class TestBatchGet:
    @pytest.mark.asyncio
    async def test_batch_get_empty_returns_empty_dict(self) -> None:
        """batch_get([]) returns {} without hitting the DB."""
        session = _make_session()
        repo = SQLAlchemyDocumentSourceMetadataRepository(session)

        result = await repo.batch_get([])

        assert result == {}
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_get_partial_returns_found_only(self) -> None:
        """batch_get with 3 ids, 2 in DB → dict with 2 entries."""
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        # Build two fake ORM rows for first two ids
        def _row(doc_id: uuid.UUID) -> MagicMock:
            r = MagicMock()
            r.doc_id = doc_id
            r.title = "Title"
            r.url = "https://example.com"
            r.published_at = None
            r.source_name = "SEC"
            r.source_type = "sec_10q"
            r.word_count = 500
            r.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            return r

        fake_result = MagicMock()
        fake_result.scalars.return_value.all.return_value = [_row(ids[0]), _row(ids[1])]
        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)

        repo = SQLAlchemyDocumentSourceMetadataRepository(session)
        result = await repo.batch_get(ids)

        assert len(result) == 2
        assert ids[0] in result
        assert ids[1] in result
        assert ids[2] not in result
