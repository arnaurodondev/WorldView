"""Unit tests: worker routes the 4 deeper Polymarket streams to the dedicated path.

PLAN-0056 Wave B3 — each new ``SourceType`` must dispatch to
``_execute_prediction_stream_task`` (NOT the standard ExecuteContentTaskUseCase
path and NOT via ADAPTER_REGISTRY), and share the longer Polymarket timeout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, SourceType
from content_ingestion.infrastructure.workers.worker import _PREDICTION_STREAM_SOURCE_TYPES

import common.ids
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_NEW_STREAM_TYPES = [
    SourceType.POLYMARKET_GAMMA_EVENTS,
    SourceType.POLYMARKET_CLOB,
    SourceType.POLYMARKET_DATA_TRADES,
    SourceType.POLYMARKET_DATA_OI,
]


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
    s.valkey_url = "redis://localhost:6379"
    s.minio_endpoint = "localhost:9000"
    s.minio_access_key = "test"
    s.minio_secret_key = "test"  # noqa: S105
    s.minio_bucket = "test-bucket"
    s.minio_secure = False
    s.http_client = MagicMock(timeout_seconds=30.0, connect_timeout_seconds=5.0)
    return s


def _make_task(source_type: SourceType) -> ContentIngestionTask:
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=f"src-{source_type.value}",
        source_type=source_type,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
    )


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
    return worker


def test_stream_source_type_set_has_exactly_four() -> None:
    assert set(_NEW_STREAM_TYPES) == set(_PREDICTION_STREAM_SOURCE_TYPES)
    assert SourceType.POLYMARKET not in _PREDICTION_STREAM_SOURCE_TYPES


@pytest.mark.parametrize("source_type", _NEW_STREAM_TYPES)
async def test_execute_task_routes_to_prediction_stream(source_type: SourceType) -> None:
    worker = _build_worker()
    worker._execute_prediction_stream_task = AsyncMock()  # type: ignore[method-assign]
    worker._execute_polymarket_task = AsyncMock()  # type: ignore[method-assign]

    task = _make_task(source_type)
    await worker._execute_task(task)

    worker._execute_prediction_stream_task.assert_awaited_once_with(task)
    worker._execute_polymarket_task.assert_not_awaited()


async def test_base_polymarket_still_routes_to_polymarket_task() -> None:
    worker = _build_worker()
    worker._execute_prediction_stream_task = AsyncMock()  # type: ignore[method-assign]
    worker._execute_polymarket_task = AsyncMock()  # type: ignore[method-assign]

    task = _make_task(SourceType.POLYMARKET)
    await worker._execute_task(task)

    worker._execute_polymarket_task.assert_awaited_once_with(task)
    worker._execute_prediction_stream_task.assert_not_awaited()


@pytest.mark.parametrize("source_type", _NEW_STREAM_TYPES)
async def test_stream_tasks_use_long_polymarket_timeout(source_type: SourceType) -> None:
    """_execute_with_semaphore must pick the 900s Polymarket timeout, not 10s."""
    worker = _build_worker()
    captured: dict[str, float] = {}

    async def _fake_execute(task: ContentIngestionTask) -> None:
        return None

    worker._execute_task = AsyncMock(side_effect=_fake_execute)  # type: ignore[method-assign]

    real_timeout = None
    orig_timeout_cls = __import__("asyncio").timeout

    def _spy_timeout(t: float) -> object:
        captured["timeout"] = t
        return orig_timeout_cls(t)

    with patch("content_ingestion.infrastructure.workers.worker.asyncio.timeout", side_effect=_spy_timeout):
        await worker._execute_with_semaphore(_make_task(source_type))

    assert captured["timeout"] == 900.0
    assert real_timeout is None  # sanity — no exceptions
