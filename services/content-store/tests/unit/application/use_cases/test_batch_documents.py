"""Unit tests for BatchDocumentsUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from content_store.application.ports.repositories import DocumentMetadataDTO
from content_store.application.use_cases.batch_documents import BatchDocumentsUseCase
from content_store.domain.errors import DomainError

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


def _make_dto(doc_id=None) -> DocumentMetadataDTO:
    return DocumentMetadataDTO(
        doc_id=doc_id or uuid4(),
        title="Test Article",
        url="https://example.com/article",
        published_at=_NOW,
        source_name=None,
        source_type="news",
        word_count=500,
    )


async def test_batch_documents_returns_found_only() -> None:
    """3 ids given, only 2 found → 2 in result; missing id silently omitted."""
    id1, id2, id3 = uuid4(), uuid4(), uuid4()
    dto1, dto2 = _make_dto(id1), _make_dto(id2)

    repo = AsyncMock()
    repo.batch_get_metadata.return_value = [dto1, dto2]

    use_case = BatchDocumentsUseCase(repo)
    result = await use_case.execute([id1, id2, id3])

    assert len(result) == 2
    assert result[0].doc_id == id1
    assert result[1].doc_id == id2
    repo.batch_get_metadata.assert_called_once_with([id1, id2, id3])


async def test_batch_documents_too_many_ids() -> None:
    """51 doc_ids → DomainError (max is 50)."""
    repo = AsyncMock()
    use_case = BatchDocumentsUseCase(repo)

    with pytest.raises(DomainError, match="Too many doc_ids"):
        await use_case.execute([uuid4() for _ in range(51)])

    repo.batch_get_metadata.assert_not_called()


async def test_batch_documents_exactly_50_ids_allowed() -> None:
    """Exactly 50 ids → no error raised."""
    repo = AsyncMock()
    repo.batch_get_metadata.return_value = []

    use_case = BatchDocumentsUseCase(repo)
    result = await use_case.execute([uuid4() for _ in range(50)])

    assert result == []
    repo.batch_get_metadata.assert_called_once()


async def test_batch_documents_empty_list() -> None:
    """Empty doc_ids list → returns empty result without calling repo."""
    repo = AsyncMock()
    use_case = BatchDocumentsUseCase(repo)

    result = await use_case.execute([])

    assert result == []
    repo.batch_get_metadata.assert_not_called()


async def test_batch_documents_all_missing() -> None:
    """All ids missing from DB → repo returns empty list → empty result."""
    repo = AsyncMock()
    repo.batch_get_metadata.return_value = []

    use_case = BatchDocumentsUseCase(repo)
    result = await use_case.execute([uuid4(), uuid4()])

    assert result == []


async def test_batch_documents_dto_fields_preserved() -> None:
    """DTO fields are passed through unmodified."""
    doc_id = uuid4()
    dto = DocumentMetadataDTO(
        doc_id=doc_id,
        title="Apple Q3 10-Q",
        url="https://sec.gov/q3",
        published_at=_NOW,
        source_name=None,
        source_type="sec_10q",
        word_count=12000,
    )
    repo = AsyncMock()
    repo.batch_get_metadata.return_value = [dto]

    use_case = BatchDocumentsUseCase(repo)
    result = await use_case.execute([doc_id])

    assert len(result) == 1
    r = result[0]
    assert r.doc_id == doc_id
    assert r.title == "Apple Q3 10-Q"
    assert r.url == "https://sec.gov/q3"
    assert r.source_type == "sec_10q"
    assert r.source_name is None
    assert r.word_count == 12000
