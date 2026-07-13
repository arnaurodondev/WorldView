"""Unit tests: prediction fetch must NOT hold a write DB session during I/O.

PLAN-0056 QA FIX 4 (R24 / S4 pool-exhaustion). The Polymarket snapshot + deeper
stream tasks previously bound the dedup callback to a session opened via
``async with self._write_factory()`` around ``adapter.fetch()`` — pinning a
write-pool connection for the entire paginated HTTP fetch + MinIO puts.

These tests assert the fix structurally:

* ``_make_dedup_exists_fn`` opens AND closes its own short-lived session per
  check (no connection left open afterwards).
* During ``adapter.fetch()`` inside ``_execute_polymarket_task`` /
  ``_execute_prediction_stream_task`` there is NO write session held open; the
  dedup callback still works (opening+closing a session just for the check).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, SourceType

import common.ids
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_WORKER_MOD = "content_ingestion.infrastructure.workers.worker"


class _SessionTracker:
    """Counts concurrently-open sessions produced by a fake ``_write_factory``."""

    def __init__(self) -> None:
        self.open_count = 0
        self.max_open = 0
        self.total_opened = 0

    def __call__(self) -> _TrackedSession:  # mimics ``self._write_factory()``
        return _TrackedSession(self)


class _TrackedSession:
    def __init__(self, tracker: _SessionTracker) -> None:
        self._t = tracker
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> _TrackedSession:
        self._t.open_count += 1
        self._t.total_opened += 1
        self._t.max_open = max(self._t.max_open, self._t.open_count)
        return self

    async def __aexit__(self, *_a: object) -> bool:
        self._t.open_count -= 1
        return False


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.db_url = "postgresql+asyncpg://u:p@localhost:5432/test"
    s.db_url_read = ""
    s.worker_batch_size = 5
    s.worker_lease_seconds = 300
    s.worker_idle_sleep_seconds = 0.01
    s.worker_concurrency = 2
    s.worker_task_timeout_seconds = 10.0
    s.worker_polymarket_task_timeout_seconds = 900.0
    s.eodhd_monthly_quota = 100_000
    s.eodhd_daily_quota = 100_000
    s.outbox_metrics_poll_seconds = 30
    s.valkey_url = "redis://localhost:6379"
    s.minio_endpoint = "localhost:9000"
    s.minio_access_key = "test"
    s.minio_secret_key = "test"  # noqa: S105
    s.minio_bucket = "test-bucket"
    s.minio_secure = False
    s.backfill_on_startup = False
    s.polymarket = MagicMock()
    return s


def _build_worker(tracker: _SessionTracker) -> object:
    with (
        patch(f"{_WORKER_MOD}._build_factories") as mock_build,
        patch(f"{_WORKER_MOD}.create_valkey_client_from_url"),
        patch(f"{_WORKER_MOD}.build_object_storage"),
    ):
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_build.return_value = (MagicMock(), MagicMock(), tracker, MagicMock())
        worker = WorkerProcess(settings=_make_settings())
    worker._http_client = AsyncMock()
    worker._storage = AsyncMock()
    return worker


def _make_task(source_type: SourceType) -> ContentIngestionTask:
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=f"src-{source_type.value}",
        source_type=source_type,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
    )


async def test_dedup_exists_fn_opens_and_closes_session_per_call() -> None:
    tracker = _SessionTracker()
    worker = _build_worker(tracker)

    with patch(f"{_WORKER_MOD}.PredictionMarketFetchLogRepository") as mock_repo_cls:
        repo = MagicMock()
        repo.exists_by_market_snapshot = AsyncMock(return_value=True)
        mock_repo_cls.return_value = repo

        fn = worker._make_dedup_exists_fn()  # type: ignore[attr-defined]
        from datetime import UTC, datetime

        result = await fn("mkt-1", datetime(2026, 7, 9, tzinfo=UTC))

    assert result is True
    # A session was opened for the check and released before returning.
    assert tracker.total_opened == 1
    assert tracker.open_count == 0
    repo.exists_by_market_snapshot.assert_awaited_once()


async def test_no_write_session_held_across_polymarket_fetch() -> None:
    tracker = _SessionTracker()
    worker = _build_worker(tracker)

    open_during_fetch: dict[str, int] = {}

    async def _fake_fetch(source: object) -> list:
        # Snapshot how many write sessions are open at fetch time — must be zero.
        open_during_fetch["at_fetch"] = tracker.open_count
        # The dedup callback still works (opening+closing its own session).
        await captured["dedup_fn"]("mkt-x", __import__("datetime").datetime.now(__import__("datetime").UTC))
        open_during_fetch["after_dedup"] = tracker.open_count
        return []

    captured: dict[str, object] = {}

    def _fake_adapter(**kwargs: object) -> MagicMock:
        captured["dedup_fn"] = kwargs["fetch_log_exists_fn"]
        adapter = MagicMock()
        adapter.fetch = AsyncMock(side_effect=_fake_fetch)
        return adapter

    with (
        patch(f"{_WORKER_MOD}.PolymarketClient"),
        patch(f"{_WORKER_MOD}.PolymarketAdapter", side_effect=_fake_adapter),
        patch(f"{_WORKER_MOD}.TaskRepository") as mock_task_repo_cls,
        patch(f"{_WORKER_MOD}.PredictionMarketFetchLogRepository") as mock_log_cls,
    ):
        mock_task_repo = MagicMock()
        mock_task_repo.update_status = AsyncMock()
        mock_task_repo_cls.return_value = mock_task_repo
        log_repo = MagicMock()
        log_repo.exists_by_market_snapshot = AsyncMock(return_value=False)
        mock_log_cls.return_value = log_repo

        await worker._execute_polymarket_task(_make_task(SourceType.POLYMARKET))  # type: ignore[attr-defined]

    # The critical R24 assertion: no write-pool session was held during fetch.
    assert open_during_fetch["at_fetch"] == 0
    # The dedup callback opened its own session and released it (net zero).
    assert open_during_fetch["after_dedup"] == 0
    # And the dedup callback did run against the fetch-log repo.
    log_repo.exists_by_market_snapshot.assert_awaited()


async def test_no_write_session_held_across_prediction_stream_fetch() -> None:
    tracker = _SessionTracker()
    worker = _build_worker(tracker)

    open_during_fetch: dict[str, int] = {}
    captured: dict[str, object] = {}

    async def _fake_fetch(source: object, *, is_backfill: bool = False) -> list:
        open_during_fetch["at_fetch"] = tracker.open_count
        return []

    def _fake_build_adapter(source_type: object, dedup_fn: object) -> MagicMock:
        captured["dedup_fn"] = dedup_fn
        adapter = MagicMock()
        adapter.fetch = AsyncMock(side_effect=_fake_fetch)
        return adapter

    with (
        patch(f"{_WORKER_MOD}.TaskRepository") as mock_task_repo_cls,
        patch("content_ingestion.infrastructure.db.repositories.source.SourceRepository") as mock_src_cls,
    ):
        mock_task_repo = MagicMock()
        mock_task_repo.update_status = AsyncMock()
        mock_task_repo_cls.return_value = mock_task_repo
        src_repo = MagicMock()
        src_repo.get_by_id = AsyncMock(return_value=MagicMock(config={"markets": []}))
        mock_src_cls.return_value = src_repo

        worker._build_prediction_stream_adapter = MagicMock(side_effect=_fake_build_adapter)  # type: ignore[attr-defined]
        worker._prediction_stream_spec = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

        await worker._execute_prediction_stream_task(  # type: ignore[attr-defined]
            _make_task(SourceType.POLYMARKET_DATA_TRADES)
        )

    assert open_during_fetch["at_fetch"] == 0
    # The dedup callback threaded into the adapter is the session-per-check wrapper.
    assert callable(captured["dedup_fn"])
