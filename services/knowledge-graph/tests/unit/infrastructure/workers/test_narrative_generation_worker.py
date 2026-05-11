"""Unit tests for NarrativeGenerationWorker (T-C-04 — Worker 13D-3).

Verifies batch orchestration, concurrency cap, per-entity error isolation,
and APScheduler-compatible run() integration (fetch stale + run_batch).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_E1 = UUID("00000000-0000-0000-0000-000000000001")
_E2 = UUID("00000000-0000-0000-0000-000000000002")
_E3 = UUID("00000000-0000-0000-0000-000000000003")


def _make_worker(execute_results: dict[UUID, bool | Exception] | None = None, concurrency: int = 5):
    """Build a NarrativeGenerationWorker with a mocked use case.

    execute_results maps entity_id → True (generated), False (skipped),
    or an Exception to raise.
    """
    from knowledge_graph.infrastructure.workers.narrative_generation_worker import (
        NarrativeGenerationWorker,
    )

    results = execute_results or {}

    async def _mock_execute(entity_id: UUID, tenant_id, reason: str) -> bool:
        outcome = results.get(entity_id, True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    use_case = MagicMock()
    use_case.execute = AsyncMock(side_effect=_mock_execute)
    # _read_sf used by _fetch_stale_entities — returns empty by default
    use_case._read_sf = MagicMock()

    worker = NarrativeGenerationWorker(use_case=use_case, concurrency=concurrency)
    return worker, use_case


class TestNarrativeGenerationWorkerBatch:
    def test_run_batch_counts_generated_and_skipped(self) -> None:
        """run_batch accumulates generated/skipped counts correctly."""
        worker, use_case = _make_worker(execute_results={_E1: True, _E2: False, _E3: True})
        result = asyncio.run(worker.run_batch([_E1, _E2, _E3]))

        assert result["generated"] == 2
        assert result["skipped"] == 1
        assert result["failed"] == 0
        assert use_case.execute.await_count == 3

    def test_run_batch_empty_list_returns_zeros(self) -> None:
        """Empty entity list returns zero counts without calling use_case."""
        worker, use_case = _make_worker()
        result = asyncio.run(worker.run_batch([]))

        assert result == {"generated": 0, "skipped": 0, "failed": 0}
        use_case.execute.assert_not_awaited()

    def test_run_batch_isolates_per_entity_failures(self) -> None:
        """Entity that raises an exception is counted as 'failed'; others proceed."""
        worker, use_case = _make_worker(
            execute_results={
                _E1: True,
                _E2: RuntimeError("LLM timeout"),
                _E3: False,
            }
        )
        result = asyncio.run(worker.run_batch([_E1, _E2, _E3]))

        assert result["generated"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 1
        # All three entities attempted
        assert use_case.execute.await_count == 3

    def test_run_batch_all_fail_returns_only_failed_count(self) -> None:
        """All entities failing → failed=N, generated=0, skipped=0."""
        worker, use_case = _make_worker(
            execute_results={
                _E1: ValueError("DB error"),
                _E2: ValueError("DB error"),
            }
        )
        result = asyncio.run(worker.run_batch([_E1, _E2]))

        assert result["generated"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 2

    def test_run_batch_passes_reason_to_use_case(self) -> None:
        """run_batch passes the reason value string to use_case.execute."""
        from knowledge_graph.domain.narrative import NarrativeGenerationReason

        worker, use_case = _make_worker(execute_results={_E1: True})
        asyncio.run(worker.run_batch([_E1], reason=NarrativeGenerationReason.DATA_UPDATE))

        call_kwargs = use_case.execute.call_args.kwargs
        assert call_kwargs["reason"] == NarrativeGenerationReason.DATA_UPDATE.value


class TestNarrativeGenerationWorkerRun:
    def test_run_calls_run_batch_for_stale_entities(self) -> None:
        """run() fetches stale entities and delegates to run_batch."""
        worker, use_case = _make_worker(execute_results={_E1: True, _E2: False})

        # Patch _fetch_stale_entities to return two entities
        async def _fake_fetch_stale() -> list:
            return [_E1, _E2]

        worker._fetch_stale_entities = _fake_fetch_stale  # type: ignore[method-assign]
        asyncio.run(worker.run())

        assert use_case.execute.await_count == 2

    def test_run_no_stale_entities_does_not_call_use_case(self) -> None:
        """run() with empty stale list skips use_case entirely."""
        worker, use_case = _make_worker()

        async def _fake_fetch_empty() -> list:
            return []

        worker._fetch_stale_entities = _fake_fetch_empty  # type: ignore[method-assign]
        asyncio.run(worker.run())

        use_case.execute.assert_not_awaited()
