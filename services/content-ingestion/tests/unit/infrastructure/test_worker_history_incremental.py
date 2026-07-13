"""Unit tests for the worker's incremental CLOB history task (PLAN-0056 QA).

Covers ``WorkerProcess._execute_history_stream_task``:
- only a BOUNDED window of ``markets_per_cycle`` markets is processed per cycle
  (round-robin via ``history_market_offset``) — the per-cycle market cap that
  stops the ``market.prediction.history.v1`` firehose,
- the rotation offset + per-market cursor are committed INCREMENTALLY (once per
  market) so a timeout/retry resumes at the next market instead of restarting,
- ``_persist_history_progress`` does a read-modify-write that preserves a
  concurrent seeder's ``markets`` list and other markets' cursors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, SourceType
from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import (
    MarketHistoryResult,
    PolymarketClobHistoryAdapter,
)

import common.ids
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.db_url = "postgresql+asyncpg://u:p@localhost:5432/test"
    s.db_url_read = ""
    s.valkey_url = "redis://localhost:6379"
    s.minio_endpoint = "localhost:9000"
    s.minio_access_key = "test"
    s.minio_secret_key = "test"  # noqa: S105
    s.minio_bucket = "test-bucket"
    s.minio_secure = False
    s.worker_batch_size = 5
    s.worker_lease_seconds = 300
    s.worker_idle_sleep_seconds = 0.01
    s.worker_concurrency = 2
    s.worker_task_timeout_seconds = 10.0
    s.worker_polymarket_task_timeout_seconds = 900.0
    s.backfill_on_startup = False
    s.polymarket_history_backfill_days = 3
    s.polymarket_clob = MagicMock(markets_per_cycle=3, max_points_per_market_per_cycle=2000)
    s.http_client = MagicMock(timeout_seconds=30.0, connect_timeout_seconds=5.0)
    return s


def _build_worker() -> MagicMock:
    with (
        patch("content_ingestion.infrastructure.workers.worker._build_factories") as mock_build,
        patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url"),
        patch("content_ingestion.infrastructure.workers.worker.build_object_storage"),
    ):
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        worker = WorkerProcess(settings=_make_settings())
    worker._http_client = AsyncMock()
    worker._write_factory = lambda: _FakeSession()  # type: ignore[method-assign]
    return worker


def _make_task() -> ContentIngestionTask:
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name="pm-clob",
        source_type=SourceType.POLYMARKET_CLOB,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
    )


async def test_per_cycle_market_cap_and_incremental_progress() -> None:
    """Only markets_per_cycle markets processed; cursor+offset committed per market."""
    worker = _build_worker()

    # 5 markets in the work-list, cap = 3 → only the first 3 processed this cycle.
    markets = [{"condition_id": f"cond_{i}", "token_ids": ["t"]} for i in range(5)]
    source_model = MagicMock(config={"markets": markets, "history_market_offset": 0})

    # Fake adapter: record fetch_market calls (by conditionId), return a cursor.
    fetch_calls: list[str] = []

    async def _fake_fetch_market(market: object, cursor: object, *, is_backfill: bool = False) -> MarketHistoryResult:
        fetch_calls.append(market.condition_id)  # type: ignore[attr-defined]
        return MarketHistoryResult(results=[], new_cursor={"last_point_ts": 1})

    fake_adapter = MagicMock()
    fake_adapter.fetch_market = _fake_fetch_market

    # Capture per-market progress persistence.
    persisted: list[tuple[str, object, int]] = []

    async def _fake_persist(source_id: object, key: str, cursor: object, resume_offset: int) -> None:
        persisted.append((key, cursor, resume_offset))

    worker._persist_history_progress = _fake_persist  # type: ignore[method-assign]
    worker._mark_stream_task_succeeded = AsyncMock()  # type: ignore[method-assign]
    worker._make_dedup_exists_fn = MagicMock(return_value=AsyncMock())  # type: ignore[method-assign]

    src_repo = MagicMock()
    src_repo.get_by_id = AsyncMock(return_value=source_model)
    task_repo = MagicMock()
    task_repo.update_status = AsyncMock()

    with (
        patch("content_ingestion.infrastructure.workers.worker.SourceRepository", return_value=src_repo),
        patch("content_ingestion.infrastructure.workers.worker.TaskRepository", return_value=task_repo),
        patch(
            "content_ingestion.infrastructure.adapters.polymarket_clob.adapter.PolymarketClobHistoryAdapter",
        ) as mock_cls,
        patch("content_ingestion.infrastructure.adapters.polymarket_clob.client.PolymarketClobHistoryClient"),
    ):
        # Building the adapter returns our fake, but the work-list reader is a
        # staticmethod called on the class — keep the REAL implementation.
        mock_cls.return_value = fake_adapter
        mock_cls._extract_markets = staticmethod(PolymarketClobHistoryAdapter._extract_markets)
        await worker._execute_history_stream_task(_make_task())

    # Per-cycle cap respected: exactly the first 3 markets fetched, in order.
    assert fetch_calls == ["cond_0", "cond_1", "cond_2"]
    # Incremental commit: progress persisted once per market with advancing offsets.
    assert [p[0] for p in persisted] == ["cond_0", "cond_1", "cond_2"]
    assert [p[2] for p in persisted] == [1, 2, 3]
    worker._mark_stream_task_succeeded.assert_awaited_once()


async def test_persist_progress_preserves_markets_and_other_cursors() -> None:
    """read-modify-write keeps the seeder's markets + other markets' cursors."""
    worker = _build_worker()

    stored_config = {
        "markets": [{"condition_id": "cond_0", "token_ids": ["t"]}],
        "history_cursors": {"cond_other": {"last_point_ts": 42}},
    }
    model = MagicMock(config=stored_config)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=model)
    repo.update = AsyncMock()

    with patch("content_ingestion.infrastructure.workers.worker.SourceRepository", return_value=repo):
        await worker._persist_history_progress(
            common.ids.new_uuid7(),
            "cond_0",
            {"last_point_ts": 99},
            resume_offset=1,
        )

    repo.update.assert_awaited_once()
    written_config = repo.update.await_args.kwargs["config"]
    # Seeder's markets preserved.
    assert written_config["markets"] == stored_config["markets"]
    # Other market's cursor preserved AND the current one written.
    assert written_config["history_cursors"]["cond_other"] == {"last_point_ts": 42}
    assert written_config["history_cursors"]["cond_0"] == {"last_point_ts": 99}
    assert written_config["history_market_offset"] == 1


def test_history_market_key_falls_back_to_token_surrogate() -> None:
    """Legacy work-items with no parent conditionId key their cursor by tokens."""
    from content_ingestion.infrastructure.adapters.polymarket_worklist import MarketWorkItem
    from content_ingestion.infrastructure.workers.worker import WorkerProcess

    with_parent = MarketWorkItem(condition_id="cond_x", token_ids=["a", "b"])
    legacy = MarketWorkItem(condition_id=None, token_ids=["a", "b"])

    assert WorkerProcess._history_market_key(with_parent) == "cond_x"
    assert WorkerProcess._history_market_key(legacy) == "a|b"
