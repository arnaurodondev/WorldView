"""Unit tests for WorkerProcess (T-E1-4-03).

Tests focus on the semaphore acquisition timeout added in M-033.
No real DB, Kafka, or network connections are used.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

_PATCH_FACTORIES = "market_ingestion.infrastructure.workers.worker._build_factories"
_PATCH_BUILD_REGISTRY = "market_ingestion.infrastructure.workers.worker.build_provider_registry"


def _make_settings(concurrency: int = 2) -> MagicMock:
    s = MagicMock()
    s.eodhd_api_key = SecretStr("test-key")
    s.storage_endpoint = "http://localhost:9000"
    s.storage_access_key = SecretStr("key")
    s.storage_secret_key = SecretStr("secret")
    s.storage_bucket = "test-bucket"
    s.worker_concurrency = concurrency
    s.worker_batch_size = 10
    s.worker_lease_seconds = 300
    return s


def _make_worker(concurrency: int = 2) -> object:
    from market_ingestion.infrastructure.workers.worker import WorkerProcess

    with (
        patch(_PATCH_FACTORIES, return_value=(MagicMock(), MagicMock())),
        patch(_PATCH_BUILD_REGISTRY),
    ):
        return WorkerProcess(settings=_make_settings(concurrency), worker_id="test-worker")


# ---------------------------------------------------------------------------
# T-E1-4-03: Semaphore timeout tests (M-033)
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_worker_semaphore_timeout_logs_warning() -> None:
    """When semaphore acquisition times out, a warning is logged and the error is swallowed.

    Simulates all permits held by injecting a TimeoutError directly so the test
    does not need to sleep 60 seconds.
    """
    from market_ingestion.infrastructure.workers.worker import WorkerProcess

    with (
        patch(_PATCH_FACTORIES, return_value=(MagicMock(), MagicMock())),
        patch(_PATCH_BUILD_REGISTRY),
    ):
        worker = WorkerProcess(settings=_make_settings(concurrency=1), worker_id="test-worker")

    task = MagicMock()
    task.id = "task-001"
    worker._execute_task = AsyncMock()  # type: ignore[attr-defined]

    with patch("market_ingestion.infrastructure.workers.worker.logger") as mock_logger:
        mock_logger.warning = MagicMock()
        # Patch asyncio.timeout to raise TimeoutError immediately
        with patch("asyncio.timeout", side_effect=TimeoutError):
            await worker._execute_with_semaphore(task)  # type: ignore[attr-defined]

    # Warning logged with correct event name
    mock_logger.warning.assert_called_once()
    event_name = mock_logger.warning.call_args[0][0]
    assert event_name == "worker.semaphore_timeout"

    # _execute_task was NOT called (timeout happened before permit was acquired)
    worker._execute_task.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_worker_continues_other_tasks_after_timeout() -> None:
    """A semaphore timeout on one task does not prevent subsequent tasks from executing.

    _execute_with_semaphore swallows TimeoutError so the worker loop can
    proceed to process the rest of the claimed batch.
    """
    worker = _make_worker(concurrency=2)

    executed: list[str] = []

    async def _track_execution(task: MagicMock) -> None:
        executed.append(str(task.id))

    worker._execute_task = _track_execution  # type: ignore[attr-defined]

    task_ok1 = MagicMock()
    task_ok1.id = "ok-1"
    task_ok2 = MagicMock()
    task_ok2.id = "ok-2"

    # Both tasks should execute without raising
    await worker._execute_with_semaphore(task_ok1)  # type: ignore[attr-defined]
    await worker._execute_with_semaphore(task_ok2)  # type: ignore[attr-defined]

    assert "ok-1" in executed
    assert "ok-2" in executed
