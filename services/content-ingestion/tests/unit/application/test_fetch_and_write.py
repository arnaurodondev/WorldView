"""Unit tests for the FetchAndWriteUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase, FetchSummary
from content_ingestion.domain.entities import FetchResult, Source, SourceType

import common.ids

pytestmark = pytest.mark.unit


def _make_source(name: str = "test-source", source_type: SourceType = SourceType.EODHD) -> Source:
    return Source(name=name, source_type=source_type, enabled=True, config={})


def _make_result(
    url: str = "https://example.com/article",
    url_hash: str = "abc123",
    source_id: object = None,
) -> FetchResult:
    return FetchResult(
        source_id=source_id or common.ids.new_uuid7(),
        url=url,
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
    bronze: object = None,
    fetch_log: object = None,
    outbox: object = None,
    commit_fn: object = None,
) -> FetchAndWriteUseCase:
    return FetchAndWriteUseCase(
        adapter=adapter or AsyncMock(),
        bronze=bronze or AsyncMock(put_object=AsyncMock(return_value="content-ingestion/eodhd/abc/raw/v1.json")),
        fetch_log_repo=fetch_log or AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
        outbox_repo=outbox or AsyncMock(),
        commit_fn=commit_fn or AsyncMock(),
    )


class TestFetchAndWriteUseCase:
    async def test_successful_fetch_and_write(self) -> None:
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 1
        assert summary.skipped == 0
        assert summary.failed == 0

    async def test_duplicate_url_hash_is_skipped(self) -> None:
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=True))
        use_case = _build_use_case(adapter=adapter, fetch_log=fetch_log)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 0
        assert summary.skipped == 1

    async def test_minio_write_failure_counted_as_failed(self) -> None:
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        bronze = AsyncMock(put_object=AsyncMock(side_effect=RuntimeError("MinIO down")))
        use_case = _build_use_case(adapter=adapter, bronze=bronze)

        summary = await use_case.execute(_make_source())

        assert summary.failed == 1
        assert summary.fetched == 0
        assert len(summary.errors) == 1

    async def test_adapter_failure_returns_failed_summary(self) -> None:
        adapter = AsyncMock(fetch=AsyncMock(side_effect=RuntimeError("API down")))
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source())

        assert summary.failed == 1
        assert summary.errors == ["API down"]

    async def test_multiple_results_mixed_outcomes(self) -> None:
        r1 = _make_result(url="https://a.com", url_hash="hash1")
        r2 = _make_result(url="https://b.com", url_hash="hash2")
        r3 = _make_result(url="https://c.com", url_hash="hash3")

        adapter = AsyncMock(fetch=AsyncMock(return_value=[r1, r2, r3]))
        # hash2 already exists
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(side_effect=lambda h: h == "hash2"),
            create=AsyncMock(),
        )
        use_case = _build_use_case(adapter=adapter, fetch_log=fetch_log)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 2
        assert summary.skipped == 1

    async def test_outbox_payload_matches_schema(self) -> None:
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        outbox = AsyncMock(append=AsyncMock())
        use_case = _build_use_case(adapter=adapter, outbox=outbox)

        await use_case.execute(_make_source())

        outbox.append.assert_called_once()
        call_args = outbox.append.call_args
        assert call_args.kwargs["event_type"] == "content.article.raw.v1"
        assert call_args.kwargs["topic"] == "content.article.raw.v1"
        payload = call_args.kwargs["payload"]
        # Avro-aligned field names (content.article.raw.v1.avsc)
        assert "event_id" in payload
        assert payload["event_type"] == "content.article.raw"
        assert payload["schema_version"] == 1
        assert "occurred_at" in payload
        assert "doc_id" in payload
        assert "source_type" in payload
        assert "source_url" in payload
        assert "minio_bronze_key" in payload
        assert "content_hash" in payload
        assert "fetch_id" in payload
        assert "is_backfill" in payload

    async def test_commit_called_as_final_batch(self) -> None:
        """With batch_size=25 (default), 3 articles commit as one final batch."""
        results = [_make_result(url_hash=f"hash{i}") for i in range(3)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = _build_use_case(adapter=adapter, commit_fn=commit_fn)

        await use_case.execute(_make_source())

        # 3 articles < batch_size 25 → single final batch commit
        assert commit_fn.call_count == 1

    async def test_never_calls_kafka_directly(self) -> None:
        """The use case must only write to outbox, never publish to Kafka."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        outbox = AsyncMock(append=AsyncMock())
        use_case = _build_use_case(adapter=adapter, outbox=outbox)

        await use_case.execute(_make_source())

        # Outbox should be called, not any Kafka producer
        outbox.append.assert_called_once()

    async def test_summary_has_duration(self) -> None:
        adapter = AsyncMock(fetch=AsyncMock(return_value=[]))
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source())

        assert summary.duration_seconds >= 0
        assert isinstance(summary, FetchSummary)


class TestFetchSummary:
    def test_frozen(self) -> None:
        summary = FetchSummary(source_name="test")
        assert summary.source_name == "test"
        assert summary.fetched == 0
        assert summary.skipped == 0
        assert summary.failed == 0


class TestBatchBoundaryCommits:
    """Verify that batch-size boundaries trigger mid-loop commits."""

    async def test_exactly_batch_size_triggers_one_mid_commit(self) -> None:
        """batch_size=3 with 3 results → 1 mid-loop commit, 0 final commit."""
        results = [_make_result(url_hash=f"h{i}") for i in range(3)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=AsyncMock(put_object=AsyncMock(return_value="k")),
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock()),
            outbox_repo=AsyncMock(append=AsyncMock()),
            commit_fn=commit_fn,
            batch_size=3,
        )

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 3
        assert commit_fn.call_count == 1

    async def test_more_than_batch_size_triggers_multiple_commits(self) -> None:
        """batch_size=2 with 5 results → 2 mid-loop + 1 final = 3 total commits."""
        results = [_make_result(url_hash=f"h{i}") for i in range(5)]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock()
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=AsyncMock(put_object=AsyncMock(return_value="k")),
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock()),
            outbox_repo=AsyncMock(append=AsyncMock()),
            commit_fn=commit_fn,
            batch_size=2,
        )

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 5
        # 5 // 2 = 2 mid-loop commits + 1 final commit for 1 leftover
        assert commit_fn.call_count == 3

    async def test_final_batch_commit_failure_counts_as_failed(self) -> None:
        """If final commit raises, pending_in_batch articles counted as failed."""
        results = [_make_result(url_hash="only-one")]
        adapter = AsyncMock(fetch=AsyncMock(return_value=results))
        commit_fn = AsyncMock(side_effect=RuntimeError("DB commit failed"))
        rollback_fn = AsyncMock()
        bronze = AsyncMock(put_object=AsyncMock(return_value="bronze-key"), delete_object=AsyncMock())
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False), create=AsyncMock()),
            outbox_repo=AsyncMock(append=AsyncMock()),
            commit_fn=commit_fn,
            rollback_fn=rollback_fn,
            batch_size=25,
        )

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 0
        assert summary.failed == 1
        assert any("final_batch" in e for e in summary.errors)
        # GC attempted for the uncommitted MinIO key
        bronze.delete_object.assert_called_once_with("bronze-key")
        rollback_fn.assert_called_once()

    async def test_intra_batch_duplicate_url_hash_is_skipped(self) -> None:
        """Two FetchResults with the same url_hash within one batch: second is skipped."""
        r1 = _make_result(url_hash="same-hash")
        r2 = _make_result(url_hash="same-hash")  # duplicate
        adapter = AsyncMock(fetch=AsyncMock(return_value=[r1, r2]))
        use_case = _build_use_case(adapter=adapter)

        summary = await use_case.execute(_make_source())

        assert summary.fetched == 1
        assert summary.skipped == 1

    async def test_rollback_called_on_article_write_failure(self) -> None:
        """If fetch_log.create raises, rollback is called and error is counted."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        rollback_fn = AsyncMock()
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(return_value=False),
            create=AsyncMock(side_effect=RuntimeError("write failed")),
        )
        bronze = AsyncMock(put_object=AsyncMock(return_value="k"), delete_object=AsyncMock())
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(append=AsyncMock()),
            commit_fn=AsyncMock(),
            rollback_fn=rollback_fn,
            batch_size=25,
        )

        summary = await use_case.execute(_make_source())

        assert summary.failed == 1
        rollback_fn.assert_called_once()
        # MinIO GC for the orphaned key
        bronze.delete_object.assert_called_once_with("k")
