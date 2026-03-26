"""Unit tests for Wave 2: watermark wiring, lock restructure, batch commit."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
from content_ingestion.domain.entities import FetchResult, Source, SourceType

import common.ids

pytestmark = pytest.mark.unit


def _make_source(name: str = "test-source", source_type: SourceType = SourceType.EODHD) -> Source:
    return Source(name=name, source_type=source_type, enabled=True, config={})


def _make_result(url_hash: str = "abc123") -> FetchResult:
    return FetchResult(
        source_id=common.ids.new_uuid7(),
        url="https://example.com/article",
        url_hash=url_hash,
        raw_bytes=b'{"title": "Test"}',
        fetched_at=datetime.now(tz=UTC),
        http_status=200,
        content_type="application/json",
        published_at=datetime.now(tz=UTC),
        is_backfill=False,
    )


def _build_use_case(
    adapter: object = None,
    commit_fn: object = None,
    rollback_fn: object = None,
    batch_size: int = 25,
) -> FetchAndWriteUseCase:
    return FetchAndWriteUseCase(
        adapter=adapter or AsyncMock(),
        bronze=AsyncMock(put_object=AsyncMock(return_value="content-ingestion/eodhd/abc/raw/v1.json")),
        fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
        outbox_repo=AsyncMock(),
        commit_fn=commit_fn or AsyncMock(),
        rollback_fn=rollback_fn,
        batch_size=batch_size,
    )


class TestBatchCommit:
    """Tests for batch commit behavior (T-R1-2-04)."""

    async def test_batch_commit_every_n_articles(self) -> None:
        """30 articles with batch_size=10 → 3 commits."""
        results = [_make_result(url_hash=f"hash{i}") for i in range(30)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = _build_use_case(adapter=adapter, commit_fn=commit_fn, batch_size=10)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 30
        assert commit_fn.call_count == 3

    async def test_final_partial_batch_committed(self) -> None:
        """7 articles with batch_size=5 → 1 full batch + 1 partial = 2 commits."""
        results = [_make_result(url_hash=f"hash{i}") for i in range(7)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = _build_use_case(adapter=adapter, commit_fn=commit_fn, batch_size=5)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 7
        assert commit_fn.call_count == 2

    async def test_single_article_commits_as_final_batch(self) -> None:
        results = [_make_result()]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = _build_use_case(adapter=adapter, commit_fn=commit_fn, batch_size=25)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 1
        assert commit_fn.call_count == 1

    async def test_error_mid_batch_rollback_resets_pending(self) -> None:
        """Error on 3rd article with batch_size=5 → rollback, subsequent articles still process."""
        results = [_make_result(url_hash=f"hash{i}") for i in range(5)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        rollback_fn = AsyncMock()

        call_count = 0

        async def flaky_put_object(**_kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("MinIO down")
            return "key"

        bronze = AsyncMock(put_object=AsyncMock(side_effect=flaky_put_object))
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
            rollback_fn=rollback_fn,
            batch_size=10,
        )

        summary = await use_case.execute(_make_source())

        assert summary.failed == 1
        assert summary.fetched == 4
        rollback_fn.assert_called()

    async def test_final_batch_commit_failure(self) -> None:
        """If final batch commit fails, articles in that batch count as failed."""
        results = [_make_result(url_hash=f"hash{i}") for i in range(3)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock(side_effect=RuntimeError("DB commit failed"))
        rollback_fn = AsyncMock()
        use_case = _build_use_case(adapter=adapter, commit_fn=commit_fn, rollback_fn=rollback_fn, batch_size=25)

        summary = await use_case.execute(_make_source())

        assert summary.failed == 3
        assert summary.fetched == 0


class TestPrefetchedResults:
    """Tests for prefetched_results parameter (T-R1-2-01 lock restructure)."""

    async def test_prefetched_skips_adapter_fetch(self) -> None:
        """When prefetched_results provided, adapter.fetch() is NOT called."""
        adapter = AsyncMock(fetch=AsyncMock())
        results = [_make_result()]
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source(), prefetched_results=results)

        adapter.fetch.assert_not_called()
        assert summary.fetched == 1

    async def test_prefetched_empty_list_returns_empty_summary(self) -> None:
        adapter = AsyncMock(fetch=AsyncMock())
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source(), prefetched_results=[])

        adapter.fetch.assert_not_called()
        assert summary.fetched == 0
        assert summary.skipped == 0


class TestFromDateWatermark:
    """Tests for from_date parameter on adapters (T-R1-2-02/03)."""

    async def test_from_date_passed_to_adapter(self) -> None:
        adapter = AsyncMock(fetch=AsyncMock(return_value=[]))
        use_case = _build_use_case(adapter=adapter)

        await use_case.execute(_make_source(), from_date="2026-03-20")

        adapter.fetch.assert_called_once()
        call_kwargs = adapter.fetch.call_args.kwargs
        assert call_kwargs["from_date"] == "2026-03-20"

    async def test_empty_from_date_by_default(self) -> None:
        adapter = AsyncMock(fetch=AsyncMock(return_value=[]))
        use_case = _build_use_case(adapter=adapter)

        await use_case.execute(_make_source())

        call_kwargs = adapter.fetch.call_args.kwargs
        assert call_kwargs["from_date"] == ""


class TestAdapterFromDateOverride:
    """Test that adapters use from_date param over config when provided (T-R1-2-03)."""

    async def test_eodhd_uses_from_date_over_config(self) -> None:
        from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter

        client = AsyncMock(fetch_all_pages=AsyncMock(return_value=[]))
        rate_limiter = AsyncMock(consume=lambda: True)
        adapter = EODHDAdapter(client=client, rate_limiter=rate_limiter)

        source = Source(
            name="test",
            source_type=SourceType.EODHD,
            enabled=True,
            config={"ticker": "AAPL", "from_date": "2020-01-01"},
        )

        await adapter.fetch(source, from_date="2026-03-20")

        client.fetch_all_pages.assert_called_once()
        call_kwargs = client.fetch_all_pages.call_args.kwargs
        assert call_kwargs["from_date"] == "2026-03-20"

    async def test_eodhd_falls_back_to_config(self) -> None:
        from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter

        client = AsyncMock(fetch_all_pages=AsyncMock(return_value=[]))
        rate_limiter = AsyncMock(consume=lambda: True)
        adapter = EODHDAdapter(client=client, rate_limiter=rate_limiter)

        source = Source(
            name="test",
            source_type=SourceType.EODHD,
            enabled=True,
            config={"ticker": "AAPL", "from_date": "2020-01-01"},
        )

        await adapter.fetch(source)

        call_kwargs = client.fetch_all_pages.call_args.kwargs
        assert call_kwargs["from_date"] == "2020-01-01"
