"""Tests for doc_id uniqueness in outbox payloads (CR-1 fix).

Verifies that each article gets a unique UUIDv7 doc_id, NOT the source_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
from content_ingestion.domain.entities import FetchResult, Source, SourceType

import common.ids

pytestmark = pytest.mark.unit

_FIXED_SOURCE_ID = common.ids.new_uuid7()


def _make_source() -> Source:
    return Source(name="test-source", source_type=SourceType.EODHD, enabled=True, config={})


def _make_result(url: str = "https://example.com/a", url_hash: str = "h1") -> FetchResult:
    return FetchResult(
        source_id=_FIXED_SOURCE_ID,
        url=url,
        url_hash=url_hash,
        raw_bytes=b'{"title": "Test"}',
        fetched_at=datetime.now(tz=UTC),
        http_status=200,
        content_type="application/json",
        published_at=datetime.now(tz=UTC),
        is_backfill=False,
    )


class TestDocIdUniqueness:
    async def test_each_article_gets_unique_doc_id(self) -> None:
        """Two articles from the same source must have different doc_ids."""
        r1 = _make_result(url="https://a.com", url_hash="hash1")
        r2 = _make_result(url="https://b.com", url_hash="hash2")
        adapter = AsyncMock(fetch=AsyncMock(return_value=[r1, r2]))
        outbox = AsyncMock(append=AsyncMock())
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        bronze = AsyncMock(put_object=AsyncMock(return_value="bronze/key"))

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            commit_fn=AsyncMock(),
        )
        await uc.execute(_make_source())

        assert outbox.append.call_count == 2
        doc_id_1 = outbox.append.call_args_list[0].kwargs["payload"]["doc_id"]
        doc_id_2 = outbox.append.call_args_list[1].kwargs["payload"]["doc_id"]
        assert doc_id_1 != doc_id_2, "Each article must get a unique doc_id"

    async def test_doc_id_is_valid_uuid(self) -> None:
        """doc_id in outbox payload must be a valid UUID string."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        outbox = AsyncMock(append=AsyncMock())
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        bronze = AsyncMock(put_object=AsyncMock(return_value="bronze/key"))

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            commit_fn=AsyncMock(),
        )
        await uc.execute(_make_source())

        doc_id = outbox.append.call_args.kwargs["payload"]["doc_id"]
        # Must be a valid UUID
        UUID(doc_id)

    async def test_source_id_not_used_as_doc_id(self) -> None:
        """doc_id must NOT be the source_id — they serve different purposes."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        outbox = AsyncMock(append=AsyncMock())
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock())
        bronze = AsyncMock(put_object=AsyncMock(return_value="bronze/key"))

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=outbox,
            commit_fn=AsyncMock(),
        )
        await uc.execute(_make_source())

        doc_id = outbox.append.call_args.kwargs["payload"]["doc_id"]
        assert doc_id != str(_FIXED_SOURCE_ID), "doc_id must not equal source_id"
