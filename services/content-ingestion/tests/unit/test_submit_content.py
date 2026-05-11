"""Unit tests for SubmitContentUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.submit_content import SubmitContentUseCase

pytestmark = pytest.mark.unit

_URL = "https://example.com/article"
_URL_HASH = "abc123"
_RAW = b"<html>content</html>"


def _make_uow(*, is_duplicate: bool = False) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.fetch_logs = AsyncMock(
        exists_by_url_hash=AsyncMock(return_value=is_duplicate),
        create=AsyncMock(),
    )
    uow.outbox = AsyncMock(append=AsyncMock())
    return uow


def _make_bronze(minio_key: str = "content-ingestion/eodhd/abc/raw/v1.json") -> AsyncMock:
    return AsyncMock(put_object=AsyncMock(return_value=minio_key))


class TestSubmitContentUseCase:
    async def test_happy_path_returns_accepted(self) -> None:
        uow = _make_uow()
        bronze = _make_bronze()
        use_case = SubmitContentUseCase(uow, bronze)

        result = await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd")

        assert result.status == "accepted"
        assert result.doc_id is not None

    async def test_duplicate_returns_without_writing(self) -> None:
        uow = _make_uow(is_duplicate=True)
        bronze = _make_bronze()
        use_case = SubmitContentUseCase(uow, bronze)

        result = await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd")

        assert result.status == "duplicate"
        bronze.put_object.assert_not_called()
        uow.fetch_logs.create.assert_not_called()
        uow.outbox.append.assert_not_called()

    async def test_commit_called_on_accepted(self) -> None:
        uow = _make_uow()
        use_case = SubmitContentUseCase(uow, _make_bronze())

        await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd")

        uow.commit.assert_called_once()

    async def test_commit_not_called_on_duplicate(self) -> None:
        uow = _make_uow(is_duplicate=True)
        use_case = SubmitContentUseCase(uow, _make_bronze())

        await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd")

        uow.commit.assert_not_called()

    async def test_bronze_put_called_with_correct_source_type(self) -> None:
        uow = _make_uow()
        bronze = _make_bronze()
        use_case = SubmitContentUseCase(uow, bronze)

        await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="sec_edgar")

        bronze.put_object.assert_called_once()
        call_kwargs = bronze.put_object.call_args.kwargs
        assert call_kwargs["source_type"] == "sec_edgar"
        assert call_kwargs["url_hash"] == _URL_HASH

    async def test_outbox_append_called(self) -> None:
        uow = _make_uow()
        use_case = SubmitContentUseCase(uow, _make_bronze())

        await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd")

        uow.outbox.append.assert_called_once()
        kwargs = uow.outbox.append.call_args.kwargs
        assert kwargs["topic"] == "content.article.raw.v1"
        payload = kwargs["payload"]
        assert payload["event_type"] == "content.article.raw"
        assert "doc_id" in payload

    async def test_published_at_passed_through(self) -> None:
        uow = _make_uow()
        bronze = _make_bronze()
        use_case = SubmitContentUseCase(uow, bronze)
        pub = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

        result = await use_case.execute(
            url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="newsapi", published_at=pub
        )

        assert result.status == "accepted"
        call_kwargs = bronze.put_object.call_args.kwargs
        assert call_kwargs["published_at"] is not None

    async def test_published_at_none_handled(self) -> None:
        uow = _make_uow()
        bronze = _make_bronze()
        use_case = SubmitContentUseCase(uow, bronze)

        result = await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="manual")

        assert result.status == "accepted"
        call_kwargs = bronze.put_object.call_args.kwargs
        assert call_kwargs["published_at"] is None

    async def test_fetch_log_source_id_is_none_for_manual(self) -> None:
        """Manual submissions have no registered source_id."""
        uow = _make_uow()
        use_case = SubmitContentUseCase(uow, _make_bronze())

        await use_case.execute(url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="manual")

        call_kwargs = uow.fetch_logs.create.call_args.kwargs
        assert call_kwargs["source_id"] is None

    async def test_each_call_generates_unique_doc_id(self) -> None:
        uow1 = _make_uow()
        uow2 = _make_uow()
        r1 = await SubmitContentUseCase(uow1, _make_bronze()).execute(
            url=_URL, url_hash=_URL_HASH, raw_bytes=_RAW, source_type="eodhd"
        )
        r2 = await SubmitContentUseCase(uow2, _make_bronze()).execute(
            url=_URL, url_hash="def456", raw_bytes=_RAW, source_type="eodhd"
        )

        assert r1.doc_id != r2.doc_id
