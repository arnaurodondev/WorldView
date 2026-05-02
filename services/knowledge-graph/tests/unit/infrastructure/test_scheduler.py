"""Unit tests for KnowledgeGraphScheduler crash instrumentation (T-A-2-01).

Verifies that worker exceptions are:
  - counted in ``s7_worker_crash_total`` with the correct worker label
  - logged at ERROR level as ``kg_worker_crashed``
  - re-raised so APScheduler can apply coalesce/retry logic
  - NOT counted when a no-op stub runs without error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from knowledge_graph.infrastructure.scheduler.scheduler import KnowledgeGraphScheduler
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

_COUNTER_PATH = "knowledge_graph.infrastructure.scheduler.scheduler.s7_worker_crash_total"


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.worker_confidence_interval_s = 60
    s.worker_contradiction_interval_s = 60
    s.worker_summary_interval_s = 60
    s.worker_definition_refresh_interval_s = 60
    s.worker_narrative_refresh_interval_s = 60
    s.worker_fundamentals_refresh_interval_s = 60
    s.worker_embedding_refresh_interval_s = 60
    s.worker_partition_interval_s = 3600
    s.worker_age_sync_interval_s = 60
    s.worker_provisional_enrichment_interval_s = 600  # PLAN-0061 T-A-1
    return s


def _make_scheduler(workers: dict | None = None) -> KnowledgeGraphScheduler:
    return KnowledgeGraphScheduler(_make_settings(), workers=workers or {})


class TestWorkerCrashInstrumentation:
    @pytest.mark.asyncio
    async def test_worker_crash_increments_counter(self) -> None:
        """When a worker raises, s7_worker_crash_total is incremented with the worker label."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(_COUNTER_PATH) as mock_counter:
            wrapped = scheduler._wrap_worker("my_worker", error_fn)
            with pytest.raises(RuntimeError):
                await wrapped()

        mock_counter.labels.assert_called_once_with(worker="my_worker")
        mock_counter.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_crash_logs_error(self) -> None:
        """When a worker raises, kg_worker_crashed is logged at ERROR with exc_info."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with capture_logs() as cap:
            with patch(_COUNTER_PATH):
                wrapped = scheduler._wrap_worker("my_worker", error_fn)
                with pytest.raises(RuntimeError):
                    await wrapped()

        assert any(
            e.get("event") == "kg_worker_crashed" and e.get("log_level") == "error" for e in cap
        ), f"Expected 'kg_worker_crashed' error log not found in: {cap}"

    @pytest.mark.asyncio
    async def test_worker_crash_reraises(self) -> None:
        """Exception is re-raised after counter increment and logging (APScheduler needs it)."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("should be reraised"))

        with patch(_COUNTER_PATH):
            wrapped = scheduler._wrap_worker("my_worker", error_fn)
            with pytest.raises(RuntimeError, match="should be reraised"):
                await wrapped()

    @pytest.mark.asyncio
    async def test_stub_does_not_increment_counter(self) -> None:
        """A no-op stub run does not trigger the crash counter."""
        scheduler = _make_scheduler()  # no workers → stubs only

        with patch(_COUNTER_PATH) as mock_counter:
            stub = scheduler._resolve_job("confidence_recompute")
            await stub()

        mock_counter.labels.assert_not_called()


class TestProvisionalEnrichmentInterval:
    @pytest.mark.asyncio
    async def test_provisional_enrichment_uses_dedicated_interval(self) -> None:
        """Scheduler wires 'worker_13e_provisional' to worker_provisional_enrichment_interval_s.

        T-A-1: The old wiring used worker_embedding_refresh_interval_s (10800s = 3h).
        The correct interval is worker_provisional_enrichment_interval_s (600s = 10min).
        We verify by checking add_job() was called with seconds=600 for that job ID.
        """
        s = _make_settings()
        s.worker_embedding_refresh_interval_s = 9999  # wrong key — must NOT be used
        s.worker_provisional_enrichment_interval_s = 600  # correct key

        scheduler = _make_scheduler(workers={})
        scheduler._settings = s

        captured: list[dict] = []

        def _capture_add_job(fn, trigger, *, seconds, id, max_instances, coalesce):  # noqa: A002
            captured.append({"seconds": seconds, "id": id})

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        prov = next((c for c in captured if c["id"] == "worker_13e_provisional"), None)
        assert prov is not None, "worker_13e_provisional job must be registered"
        assert prov["seconds"] == 600, (
            f"Expected 600s interval for worker_13e_provisional, got {prov['seconds']}. "
            "The job must use worker_provisional_enrichment_interval_s, not "
            "worker_embedding_refresh_interval_s."
        )
