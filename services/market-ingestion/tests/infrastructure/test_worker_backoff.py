"""Unit tests for WorkerProcess exponential backoff in _claim_batch (M-008).

Verifies that:
  - Repeated DB failures cause sleep durations to increase exponentially.
  - A successful claim resets the backoff to zero.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

_PATCH_FACTORIES = "market_ingestion.infrastructure.workers.worker._build_factories"
_PATCH_BUILD_REGISTRY = "market_ingestion.infrastructure.workers.worker.build_provider_registry"


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.eodhd_api_key = SecretStr("test-key")
    s.storage_endpoint = "http://localhost:9000"
    s.storage_access_key = SecretStr("key")
    s.storage_secret_key = SecretStr("secret")
    s.storage_bucket = "test-bucket"
    s.worker_concurrency = 2
    s.worker_batch_size = 10
    s.worker_lease_seconds = 300
    return s


def _make_worker(idle_sleep: float = 5.0) -> object:
    from market_ingestion.infrastructure.workers.worker import WorkerProcess

    with (
        patch(_PATCH_FACTORIES, return_value=(MagicMock(), MagicMock())),
        patch(_PATCH_BUILD_REGISTRY),
    ):
        return WorkerProcess(
            settings=_make_settings(),
            worker_id="test-worker",
            idle_sleep_seconds=idle_sleep,
        )


# ---------------------------------------------------------------------------
# M-008: Exponential backoff tests
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_backoff_increases_on_repeated_failures() -> None:
    """Three consecutive DB failures must produce increasing sleep durations.

    With idle_sleep=5s the sequence is:
      failure 1: backoff = 0*2 + 5 = 5s
      failure 2: backoff = 5*2 + 5 = 15s
      failure 3: backoff = 15*2 + 5 = 35s
    """
    worker = _make_worker(idle_sleep=5.0)
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    exc = RuntimeError("db gone")

    with (
        patch("market_ingestion.infrastructure.workers.worker.ClaimTasksUseCase") as mock_claim_cls,
        patch("asyncio.sleep", side_effect=_fake_sleep),
    ):
        mock_use_case = MagicMock()
        mock_use_case.execute = AsyncMock(side_effect=exc)
        mock_claim_cls.return_value = mock_use_case

        # Three failures
        await worker._claim_batch()  # type: ignore[attr-defined]
        await worker._claim_batch()  # type: ignore[attr-defined]
        await worker._claim_batch()  # type: ignore[attr-defined]

    assert len(sleep_calls) == 3, f"expected 3 sleep calls, got {sleep_calls}"
    # Each backoff must be strictly greater than the previous one
    assert sleep_calls[0] < sleep_calls[1] < sleep_calls[2], f"backoff must increase: {sleep_calls}"
    # First backoff: 0*2 + 5 = 5
    assert sleep_calls[0] == pytest.approx(5.0)
    # Second: 5*2 + 5 = 15
    assert sleep_calls[1] == pytest.approx(15.0)
    # Third: 15*2 + 5 = 35
    assert sleep_calls[2] == pytest.approx(35.0)


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_backoff_capped_at_60_seconds() -> None:
    """Backoff must not exceed 60 s regardless of how many consecutive failures occur."""
    worker = _make_worker(idle_sleep=5.0)
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    exc = RuntimeError("db gone")

    with (
        patch("market_ingestion.infrastructure.workers.worker.ClaimTasksUseCase") as mock_claim_cls,
        patch("asyncio.sleep", side_effect=_fake_sleep),
    ):
        mock_use_case = MagicMock()
        mock_use_case.execute = AsyncMock(side_effect=exc)
        mock_claim_cls.return_value = mock_use_case

        # Run enough iterations to overflow the cap
        for _ in range(6):
            await worker._claim_batch()  # type: ignore[attr-defined]

    assert all(s <= 60.0 for s in sleep_calls), f"backoff exceeded 60s cap: {sleep_calls}"
    # After enough iterations the value should be pinned at 60
    assert sleep_calls[-1] == pytest.approx(60.0)


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_backoff_resets_on_success() -> None:
    """After a successful claim the backoff must reset to 0.

    Sequence: 2 failures (backoff grows) → 1 success → 1 failure (backoff starts from 0 again).
    """
    worker = _make_worker(idle_sleep=5.0)
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    exc = RuntimeError("transient error")

    task_mock = MagicMock()
    task_mock.id = "task-1"

    call_count = 0

    async def _side_effect(*_args: object, **_kwargs: object) -> list[object]:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise exc
        if call_count == 3:
            return [task_mock]  # success
        raise exc  # 4th call fails again

    with (
        patch("market_ingestion.infrastructure.workers.worker.ClaimTasksUseCase") as mock_claim_cls,
        patch("asyncio.sleep", side_effect=_fake_sleep),
    ):
        mock_use_case = MagicMock()
        mock_use_case.execute = AsyncMock(side_effect=_side_effect)
        mock_claim_cls.return_value = mock_use_case

        await worker._claim_batch()  # failure 1 → backoff=5
        await worker._claim_batch()  # failure 2 → backoff=15
        await worker._claim_batch()  # success  → backoff reset to 0 (no sleep)
        await worker._claim_batch()  # failure 3 → backoff=5 again (reset worked)

    # Only 3 sleeps: the success call must NOT sleep, and failure-after-reset starts at 5
    assert len(sleep_calls) == 3, f"expected 3 sleeps (2 failures + 1 post-reset failure), got {sleep_calls}"
    assert sleep_calls[0] == pytest.approx(5.0)  # first failure
    assert sleep_calls[1] == pytest.approx(15.0)  # second failure
    assert sleep_calls[2] == pytest.approx(5.0)  # post-reset failure — back to base
