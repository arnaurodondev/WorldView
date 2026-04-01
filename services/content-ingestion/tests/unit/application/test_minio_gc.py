"""Unit tests for MinIO orphan GC on DB rollback in FetchAndWriteUseCase (T-R3-3-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
from content_ingestion.domain.entities import FetchResult, Source, SourceType

import common.ids

pytestmark = pytest.mark.unit

_MINIO_KEY = "content-ingestion/eodhd/abc123/raw/v1.json"


def _make_source() -> Source:
    return Source(name="test", source_type=SourceType.EODHD, enabled=True, config={})


def _make_result(url_hash: str = "hash1") -> FetchResult:
    return FetchResult(
        source_id=common.ids.new_uuid7(),
        url=f"https://example.com/{url_hash}",
        url_hash=url_hash,
        raw_bytes=b'{"title": "Test"}',
        fetched_at=datetime.now(tz=UTC),
        http_status=200,
        content_type="application/json",
        published_at=None,
        is_backfill=False,
    )


def _build_use_case(
    *,
    bronze: object = None,
    fetch_log: object = None,
    outbox: object = None,
    commit_fn: object = None,
    rollback_fn: object = None,
) -> FetchAndWriteUseCase:
    return FetchAndWriteUseCase(
        adapter=AsyncMock(fetch=AsyncMock(return_value=[])),
        bronze=bronze
        or AsyncMock(
            put_object=AsyncMock(return_value=_MINIO_KEY),
            delete_object=AsyncMock(),
        ),
        fetch_log_repo=fetch_log or AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
        outbox_repo=outbox or AsyncMock(),
        commit_fn=commit_fn or AsyncMock(),
        rollback_fn=rollback_fn,
    )


class TestMinioGCOnRollback:
    async def test_db_write_failure_deletes_orphaned_bronze_key(self) -> None:
        """DB write fails → rollback → delete_object called for the written key."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        bronze = AsyncMock(
            put_object=AsyncMock(return_value=_MINIO_KEY),
            delete_object=AsyncMock(),
        )
        # fetch_log.create raises (simulates DB write failure)
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(return_value=False),
            create=AsyncMock(side_effect=RuntimeError("DB error")),
        )
        rollback = AsyncMock()

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
            rollback_fn=rollback,
        )
        summary = await uc.execute(_make_source())

        assert summary.failed == 1
        bronze.delete_object.assert_called_once_with(_MINIO_KEY)

    async def test_gc_failure_does_not_propagate(self) -> None:
        """If delete_object raises, the exception must not propagate to the caller."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        bronze = AsyncMock(
            put_object=AsyncMock(return_value=_MINIO_KEY),
            delete_object=AsyncMock(side_effect=RuntimeError("MinIO down")),
        )
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(return_value=False),
            create=AsyncMock(side_effect=RuntimeError("DB error")),
        )

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )
        # Must NOT raise even though delete_object fails
        summary = await uc.execute(_make_source())
        assert summary.failed == 1

    async def test_committed_batch_not_deleted(self) -> None:
        """After a successful commit, delete_object must NOT be called."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        bronze = AsyncMock(
            put_object=AsyncMock(return_value=_MINIO_KEY),
            delete_object=AsyncMock(),
        )

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
        )
        summary = await uc.execute(_make_source())

        assert summary.fetched == 1
        bronze.delete_object.assert_not_called()

    async def test_suppressed_article_produces_no_gc(self) -> None:
        """Skipped (duplicate) articles are never written to MinIO — no GC needed."""
        result = _make_result()
        adapter = AsyncMock(fetch=AsyncMock(return_value=[result]))
        bronze = AsyncMock(
            put_object=AsyncMock(return_value=_MINIO_KEY),
            delete_object=AsyncMock(),
        )
        # Simulate duplicate URL hash
        fetch_log = AsyncMock(exists_by_url_hash=AsyncMock(return_value=True))

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
        )
        summary = await uc.execute(_make_source())

        assert summary.skipped == 1
        bronze.put_object.assert_not_called()
        bronze.delete_object.assert_not_called()

    async def test_final_batch_commit_failure_deletes_pending_keys(self) -> None:
        """When the final-batch commit fails, all pending MinIO keys are GC'd."""
        r1 = _make_result("hash1")
        r2 = _make_result("hash2")
        adapter = AsyncMock(fetch=AsyncMock(return_value=[r1, r2]))

        keys = ["key1", "key2"]
        bronze = AsyncMock(
            put_object=AsyncMock(side_effect=keys),
            delete_object=AsyncMock(),
        )
        commit = AsyncMock(side_effect=RuntimeError("commit failed"))

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=AsyncMock(exists_by_url_hash=AsyncMock(return_value=False)),
            outbox_repo=AsyncMock(),
            commit_fn=commit,
            rollback_fn=AsyncMock(),
        )
        summary = await uc.execute(_make_source())

        assert summary.failed > 0
        # Both keys must be deleted
        bronze.delete_object.assert_any_call("key1")
        bronze.delete_object.assert_any_call("key2")

    async def test_multiple_articles_batch_only_gc_uncommitted(self) -> None:
        """Keys from a successfully committed batch must never be GC'd."""
        # 3 articles: first 2 commit in a batch (batch_size=2), third fails
        r1 = _make_result("hash1")
        r2 = _make_result("hash2")
        r3 = _make_result("hash3")
        adapter = AsyncMock(fetch=AsyncMock(return_value=[r1, r2, r3]))

        bronze = AsyncMock(
            put_object=AsyncMock(side_effect=["key1", "key2", "key3"]),
            delete_object=AsyncMock(),
        )
        # Commit succeeds for first batch, r3's fetch_log.create fails
        fetch_log = AsyncMock(
            exists_by_url_hash=AsyncMock(return_value=False),
            create=AsyncMock(side_effect=[None, None, RuntimeError("DB error on r3")]),
        )

        uc = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log,
            outbox_repo=AsyncMock(),
            commit_fn=AsyncMock(),
            rollback_fn=AsyncMock(),
            batch_size=2,  # first 2 articles commit together
        )
        await uc.execute(_make_source())

        # key1 and key2 were committed — must NOT be deleted
        delete_calls = [c.args[0] for c in bronze.delete_object.call_args_list]
        assert "key1" not in delete_calls
        assert "key2" not in delete_calls
        # key3 is the orphaned key
        assert "key3" in delete_calls
