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
    path_engine: MagicMock | None = None,
    scorer: MagicMock | None = None,
    template_matcher: MagicMock | None = None,
    instance_uuid: UUID | None = None,
    batch_size: int = 10,
) -> object:
    from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

    if session_factory is None:
        session_factory, _ = _make_session_factory()
    if path_engine is None:
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=[])
    if scorer is None:
        scorer = MagicMock()
    if template_matcher is None:
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

    return PathInsightWorker(
        session_factory=session_factory,
        path_engine=path_engine,
        scorer=scorer,
        template_matcher=template_matcher,
        instance_uuid=instance_uuid or uuid4(),
        batch_size=batch_size,
    )


class TestPathInsightWorker:
    def test_worker_uses_graph_path_engine(self) -> None:
        """Worker claims jobs and calls the GraphPathEngine for each job entity_id."""
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()
        entity_id = job.entity_id  # type: ignore[attr-defined]

        session_factory, _session = _make_session_factory()
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=[])
        scorer = MagicMock()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
            scorer=scorer,
            template_matcher=template_matcher,
            instance_uuid=uuid4(),
        )

        asyncio.run(worker._process_job(job))
        # Engine is called with the anchor entity_id (PLAN-0112 T-2-04).
        path_engine.find_paths_from_anchor.assert_awaited_once()
        call = path_engine.find_paths_from_anchor.await_args
        assert call.args[0] == entity_id

    def test_worker_passes_prune_membership(self) -> None:
        """Worker requests membership-pruned discovery at the configured hop cap."""
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()

        session_factory, _session = _make_session_factory()
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=[])

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=uuid4(),
            path_max_hops=4,
        )

        asyncio.run(worker._process_job(job))
        call = path_engine.find_paths_from_anchor.await_args
        assert call.kwargs["prune_membership"] is True
        assert call.kwargs["max_hops"] == 4

    def test_worker_filters_self_loops(self) -> None:
        """Paths whose endpoints are the same entity are dropped before scoring."""
        from knowledge_graph.application.ports.graph_path_engine import RawPath
        from knowledge_graph.application.services.path_scorer import PathScorer
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()
        same_id = str(uuid4())
        # A self-loop path: first and last node ids identical.
        self_loop = RawPath(
            node_ids=(same_id, str(uuid4()), same_id),
            node_names=("A", "B", "A"),
            node_types=("company", "company", "company"),
            rel_types=("SUPPLIER_OF", "SUPPLIER_OF"),
            edge_confs=(0.8, 0.8),
        )
        good = _make_raw_path(2)

        session_factory, _session = _make_session_factory()
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=[self_loop, good])

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
            scorer=PathScorer(),
            template_matcher=AsyncMock(),
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

        worker._template_matcher.match = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        worker._insight_repo = lambda session: _FakeInsightRepo()  # type: ignore[method-assign]
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._process_job(job))
        # Only the non-self-loop path is scored/persisted.
        assert len(captured) == 1

    def test_worker_failure_increments_retry(self) -> None:
        """When path_discovery raises, mark_failed is called (BP-113)."""
        from unittest.mock import AsyncMock, MagicMock

        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        job = _make_job()

        session_factory, _session = _make_session_factory()
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(side_effect=RuntimeError("AGE error"))

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
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
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=raw_paths)

        scorer = PathScorer()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
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
        path_engine = AsyncMock()
        path_engine.find_paths_from_anchor = AsyncMock(return_value=raw_paths)
        scorer = PathScorer()
        template_matcher = AsyncMock()
        template_matcher.match = AsyncMock(return_value=None)

        worker = PathInsightWorker(
            session_factory=session_factory,
            path_engine=path_engine,
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
            path_engine=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=uuid4(),
            batch_size=7,
        )
        worker._job_repo = lambda session: _FakeJobRepo()  # type: ignore[method-assign]

        asyncio.run(worker._claim_batch())
        assert claimed_batch_sizes == [7]

    @pytest.mark.asyncio
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
            path_engine=AsyncMock(),
            scorer=MagicMock(),
            template_matcher=AsyncMock(),
            instance_uuid=worker_a_uuid,
        )
        worker_b = PathInsightWorker(
            session_factory=sf_b,
            path_engine=AsyncMock(),
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
            path_engine=AsyncMock(),
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


# ── PLAN-0112 W3 live-QA fixes: novelty first_seen fallback + dst FK guard ──────


class _Result:
    """Minimal fake SQLAlchemy result for mocked sessions."""

    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list:
        return self._rows


class TestFetchFirstSeenFallback:
    """BUG 1: novelty was 0 for every path because the AGE edge ``relation_id``
    is often absent from ``relations`` (sync gap) — first_seen must COALESCE in
    ``relation_evidence.MIN(evidence_date)``.
    """

    def test_first_seen_query_coalesces_relation_evidence(self) -> None:
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        rid = uuid4()
        captured: dict[str, str] = {}

        async def _execute(stmt, params=None):
            captured["sql"] = str(getattr(stmt, "text", stmt))
            return _Result([(str(rid), _NOW)])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)

        out = asyncio.run(PathInsightWorker._fetch_first_seen(session, {rid}))
        # The fallback source MUST be queried.
        assert "relation_evidence" in captured["sql"]
        assert "COALESCE" in captured["sql"].upper()
        assert out[rid] == _NOW

    def test_empty_rel_ids_returns_empty(self) -> None:
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        session = AsyncMock()
        session.execute = AsyncMock()
        out = asyncio.run(PathInsightWorker._fetch_first_seen(session, set()))
        assert out == {}
        session.execute.assert_not_called()


class TestScoreWithWeirdnessDstGuard:
    """BUG 2: a path ending on a non-canonical entity_id must persist with
    dst_entity_id=NULL (no FK violation), and rel_ids must flow into novelty.
    """

    def _make_settings(self):
        from knowledge_graph.config import Settings

        return Settings(
            database_url="postgresql://u:p@localhost/db",
            storage_access_key="k",
            storage_secret_key="s",
        )

    def _routed_session(
        self,
        *,
        canonical_ids: set,
        first_seen_rows: list,
    ):
        """Session whose execute routes each prefetch query to canned rows."""

        async def _execute(stmt, params=None):
            sql = str(getattr(stmt, "text", stmt))
            if "FROM node_degree" in sql:
                return _Result([])  # degree map empty → fail-open degree 1
            if "FROM graph_stats" in sql:
                return _Result()  # get_graph_stats → fetchone None handled below
            if "entity_embedding_state" in sql:
                return _Result([])
            if "relation_evidence" in sql or "first_evidence_at" in sql:
                return _Result(first_seen_rows)
            if "FROM canonical_entities" in sql:
                return _Result([(str(e),) for e in canonical_ids])
            return _Result([])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    def test_non_canonical_endpoint_nulls_dst(self) -> None:
        from knowledge_graph.application.ports.graph_path_engine import RawPath
        from knowledge_graph.application.ports.node_degree_repository import GraphStats
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        src = uuid4()
        mid = uuid4()
        non_canonical_dst = uuid4()
        rid1, rid2 = uuid4(), uuid4()
        raw = RawPath(
            node_ids=(str(src), str(mid), str(non_canonical_dst)),
            node_names=("Src", "Mid", "Dst"),
            node_types=("company", "company", "person"),
            rel_types=("REGULATES", "REGULATES"),
            edge_confs=(1.0, 1.0),
            rel_ids=(rid1, rid2),
        )

        session = self._routed_session(
            canonical_ids={src, mid},  # dst is NOT canonical
            first_seen_rows=[(str(rid1), _NOW)],
        )
        factory = MagicMock(return_value=session)

        from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
            NodeDegreeRepository,
        )

        with patch.object(NodeDegreeRepository, "get_graph_stats", AsyncMock(return_value=GraphStats(10, 8, 5))):
            worker = PathInsightWorker(
                session_factory=factory,
                path_engine=AsyncMock(),
                scorer=MagicMock(),
                template_matcher=AsyncMock(),
                instance_uuid=uuid4(),
                node_degree_repo_factory=NodeDegreeRepository,
                settings=self._make_settings(),
            )
            insights = asyncio.run(worker._score_with_weirdness([raw]))

        assert len(insights) == 1
        # dst is non-canonical → must be NULLed to avoid the FK violation.
        assert insights[0].dst_entity_id is None

    def test_canonical_endpoint_keeps_dst_and_novelty_nonzero(self) -> None:
        from knowledge_graph.application.ports.graph_path_engine import RawPath
        from knowledge_graph.application.ports.node_degree_repository import GraphStats
        from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

        src = uuid4()
        mid = uuid4()
        dst = uuid4()
        rid1, rid2 = uuid4(), uuid4()
        # Use a first_seen well within the 7-day window so novelty > 0.
        from common.time import utc_now  # type: ignore[import-untyped]

        recent = utc_now()
        raw = RawPath(
            node_ids=(str(src), str(mid), str(dst)),
            node_names=("Src", "Mid", "Dst"),
            node_types=("company", "company", "person"),
            rel_types=("REGULATES", "REGULATES"),
            edge_confs=(1.0, 1.0),
            rel_ids=(rid1, rid2),
        )

        session = self._routed_session(
            canonical_ids={src, mid, dst},  # all canonical
            first_seen_rows=[(str(rid1), recent), (str(rid2), recent)],
        )
        factory = MagicMock(return_value=session)

        from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
            NodeDegreeRepository,
        )

        with patch.object(NodeDegreeRepository, "get_graph_stats", AsyncMock(return_value=GraphStats(10, 8, 5))):
            worker = PathInsightWorker(
                session_factory=factory,
                path_engine=AsyncMock(),
                scorer=MagicMock(),
                template_matcher=AsyncMock(),
                instance_uuid=uuid4(),
                node_degree_repo_factory=NodeDegreeRepository,
                settings=self._make_settings(),
            )
            insights = asyncio.run(worker._score_with_weirdness([raw]))

        assert insights[0].dst_entity_id == dst
        # rel_id flowed into the novelty term (recent edge → novelty == 1.0).
        assert insights[0].novelty == pytest.approx(1.0)
