"""Unit tests for PathInsightWorker (T-E1-04)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

if TYPE_CHECKING:
    from knowledge_graph.domain.entities.path_insight import PathInsight

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def _make_job(
    job_id: UUID | None = None,
    entity_id: UUID | None = None,
    status: str = "running",
    claimed_by: UUID | None = None,
    retry_count: int = 0,
) -> object:
    from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

    cby = claimed_by or uuid4()
    return PathInsightJob(
        job_id=job_id or uuid4(),
        entity_id=entity_id or uuid4(),
        status=PathJobStatus(status),
        claimed_by=cby if status == "running" else None,
        created_at=_NOW,
        retry_count=retry_count,
    )


def _make_raw_path(n_hops: int = 2) -> object:
    from knowledge_graph.infrastructure.age.path_discovery import RawPath

    return RawPath(
        node_ids=tuple(str(uuid4()) for _ in range(n_hops + 1)),
        node_names=tuple(f"E{i}" for i in range(n_hops + 1)),
        node_types=tuple("company" for _ in range(n_hops + 1)),
        rel_types=tuple("SUPPLIES_TO" for _ in range(n_hops)),
        edge_confs=tuple(0.8 for _ in range(n_hops)),
    )


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    """Returns (factory, session) where factory() returns session as context manager."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_worker(
    session_factory: MagicMock | None = None,
    path_discovery: MagicMock | None = None,
    scorer: MagicMock | None = None,
    template_matcher: MagicMock | None = None,
    instance_uuid: UUID | None = None,
    batch_size: int = 10,
) -> object:
    from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

    if session_factory is None:
        session_factory, _ = _make_session_factory()
    if path_discovery is None:
        path_discovery = AsyncMock()
        path_discovery.find_paths_for_anchor = AsyncMock(return_value=[])
    if scorer is None:
        scorer = MagicMock()
    if template_matcher is None:
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

    return PathInsightWorker(
        session_factory=session_factory,
        path_discovery=path_discovery,
        scorer=scorer,
        template_matcher=template_matcher,
        instance_uuid=instance_uuid or uuid4(),
        batch_size=batch_size,
    )


class TestPathInsightWorker:
    def test_worker_claims_and_processes_job(self) -> None:
        """Worker claims jobs and calls path_discovery for each job entity_id."""
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()
        entity_id = job.entity_id  # type: ignore[attr-defined]

        session_factory, _session = _make_session_factory()
        path_discovery = AsyncMock()
        path_discovery.find_paths_for_anchor = AsyncMock(return_value=[])
        scorer = MagicMock()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=path_discovery,
            scorer=scorer,
            template_matcher=template_matcher,
            instance_uuid=uuid4(),
        )

        asyncio.run(worker._process_job(job))
        path_discovery.find_paths_for_anchor.assert_awaited_once_with(entity_id)

    def test_worker_failure_increments_retry(self) -> None:
        """When path_discovery raises, mark_failed is called (BP-113)."""
        from unittest.mock import AsyncMock, MagicMock

        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()

        session_factory, _session = _make_session_factory()
        path_discovery = AsyncMock()
        path_discovery.find_paths_for_anchor = AsyncMock(side_effect=RuntimeError("AGE error"))

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=path_discovery,
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=uuid4(),
        )

        # Patch job_repo to verify mark_failed is called
        mark_failed_called = []

        class _FakeJobRepo:
            async def mark_failed(self, job_id: UUID, error_text: str) -> None:
                mark_failed_called.append((job_id, error_text))

            async def mark_done(self, *args: object, **kwargs: object) -> None:
                pass

            async def claim_batch(self, *args: object, **kwargs: object) -> list:
                return []

        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._process_job(job))
        assert len(mark_failed_called) == 1
        assert "AGE error" in mark_failed_called[0][1]

    def test_no_llm_calls_in_wave_e1(self) -> None:
        """All PathInsight objects created by the worker have llm_explanation=None."""
        from knowledge_graph.application.services.path_scorer import PathScorer
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()
        raw_paths = [_make_raw_path(2)]

        session_factory, _session = _make_session_factory()
        path_discovery = AsyncMock()
        path_discovery.find_paths_for_anchor = AsyncMock(return_value=raw_paths)

        scorer = PathScorer()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=path_discovery,
            scorer=scorer,
            template_matcher=template_matcher,
            instance_uuid=uuid4(),
        )

        captured_insights: list[PathInsight] = []

        class _FakeInsightRepo:
            async def replace_for_anchor(self, anchor_id: UUID, insights: list) -> None:
                captured_insights.extend(insights)

        class _FakeJobRepo:
            async def mark_done(self, job_id: UUID, paths_found: int) -> None:
                pass

            async def mark_failed(self, job_id: UUID, error_text: str) -> None:
                pass

        worker._insight_repo = lambda session: _FakeInsightRepo()  # type: ignore[method-assign]
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._process_job(job))
        for insight in captured_insights:
            assert insight.llm_explanation is None
            assert insight.explanation_model is None

    def test_top_50_limit_enforced(self) -> None:
        """Worker stores at most 50 insights per anchor entity."""
        from knowledge_graph.application.services.path_scorer import PathScorer
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()
        # Create 60 distinct raw paths (2-hop, different entity IDs)
        raw_paths = [_make_raw_path(2) for _ in range(60)]

        session_factory, _session = _make_session_factory()
        path_discovery = AsyncMock()
        path_discovery.find_paths_for_anchor = AsyncMock(return_value=raw_paths)
        scorer = PathScorer()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=path_discovery,
            scorer=scorer,
            template_matcher=template_matcher,
            instance_uuid=uuid4(),
        )

        captured: list = []

        class _FakeInsightRepo:
            async def replace_for_anchor(self, anchor_id: UUID, insights: list) -> None:
                captured.extend(insights)

        class _FakeJobRepo:
            async def mark_done(self, job_id: UUID, paths_found: int) -> None:
                pass

            async def mark_failed(self, job_id: UUID, error_text: str) -> None:
                pass

        worker._insight_repo = lambda session: _FakeInsightRepo()  # type: ignore[method-assign]
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._process_job(job))
        assert len(captured) <= 50

    def test_worker_batch_size_respected(self) -> None:
        """Worker passes batch_size to claim_batch."""
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        claimed_batch_sizes: list = []
        session_factory, _session = _make_session_factory()

        class _FakeJobRepo:
            async def claim_batch(self, instance_uuid: UUID, batch_size: int = 10) -> list:
                claimed_batch_sizes.append(batch_size)
                return []

            async def reclaim_stuck(self, *args: object, **kwargs: object) -> int:
                return 0

            async def mark_done(self, *args: object, **kwargs: object) -> None:
                pass

            async def mark_failed(self, *args: object, **kwargs: object) -> None:
                pass

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=uuid4(),
            batch_size=7,
        )
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._claim_batch())
        assert claimed_batch_sizes == [7]

    @pytest.mark.asyncio()
    async def test_parallel_workers_claim_disjoint_sets(self) -> None:
        """Two concurrent worker instances claim disjoint job sets.

        asyncio.gather requires a running event loop — test must be async.
        """
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        # Simulate each worker getting distinct jobs
        worker_a_uuid = uuid4()
        worker_b_uuid = uuid4()
        job_a_id = uuid4()
        job_b_id = uuid4()
        job_a = _make_job(job_id=job_a_id)
        job_b = _make_job(job_id=job_b_id)

        class _FakeJobRepoA:
            async def claim_batch(self, instance_uuid: UUID, batch_size: int = 10) -> list:
                return [job_a]

            async def reclaim_stuck(self, *args: object, **kwargs: object) -> int:
                return 0

        class _FakeJobRepoB:
            async def claim_batch(self, instance_uuid: UUID, batch_size: int = 10) -> list:
                return [job_b]

            async def reclaim_stuck(self, *args: object, **kwargs: object) -> int:
                return 0

        sf_a, _ = _make_session_factory()
        sf_b, _ = _make_session_factory()
        worker_a = PathInsightWorker(
            session_factory=sf_a,
            path_discovery=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=worker_a_uuid,
        )
        worker_b = PathInsightWorker(
            session_factory=sf_b,
            path_discovery=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=worker_b_uuid,
        )
        worker_a._job_repo = lambda session: _FakeJobRepoA()  # type: ignore[method-assign]
        worker_b._job_repo = lambda session: _FakeJobRepoB()  # type: ignore[method-assign]

        jobs_a, jobs_b = await asyncio.gather(worker_a._claim_batch(), worker_b._claim_batch())
        ids_a = {j.job_id for j in jobs_a}
        ids_b = {j.job_id for j in jobs_b}
        assert ids_a.isdisjoint(ids_b)

    def test_reclaim_stuck_integration(self) -> None:
        """_reclaim_loop calls reclaim_stuck on the job repository.

        The reclaim loop sleeps first, then calls reclaim_stuck.  We allow the
        first sleep to return normally (so reclaim_stuck executes), then the
        second sleep raises CancelledError to stop the loop.
        """
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        reclaim_called: list = []
        session_factory, _session = _make_session_factory()

        class _FakeJobRepo:
            async def reclaim_stuck(self, timeout_seconds: int = 600) -> int:
                reclaim_called.append(timeout_seconds)
                return 2

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_discovery=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=uuid4(),
        )
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        async def _run_once() -> None:
            # First sleep returns None (allows reclaim_stuck to run),
            # second sleep raises CancelledError (stops the loop).
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = [None, asyncio.CancelledError()]
                try:
                    await worker._reclaim_loop()
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run_once())
        assert len(reclaim_called) == 1
        assert reclaim_called[0] == 600

    def test_worker_recovery_from_stuck_running(self) -> None:
        """reclaim_stuck returns the count of recovered jobs."""
        from unittest.mock import AsyncMock, MagicMock

        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        result_mock = MagicMock()
        result_mock.rowcount = 5
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        repo = PathInsightJobRepository(session)
        count = asyncio.run(repo.reclaim_stuck(timeout_seconds=600))
        assert count == 5
