"""PathInsightWorker — processes path_insight_jobs using AGE multi-hop discovery (T-E1-04).

Runs as a standalone worker process (R22).  Claims jobs from the
``path_insight_jobs`` table using SKIP LOCKED, discovers multi-hop paths via
Apache AGE, scores them, and writes the top-50 to ``path_insights``.

BP-112 pattern: a separate reclaim loop resets any jobs stuck in 'running'
for more than 10 minutes back to 'pending' so they can be retried.

BP-113 pattern: ALL exceptions in _process_job are caught and routed to
mark_failed — a job is never left permanently stuck in 'running'.

ADR-0074-001: llm_explanation=None in all PathInsight objects (Wave E2 deferred).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.services.path_scorer import PathScorer
    from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher
    from knowledge_graph.domain.entities.path_insight import PathInsightJob
    from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
        PathInsightJobRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
        PathInsightRepository,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum insights stored per anchor entity (PRD-0074 §9.3).
_TOP_K = 50

# Sleep when no jobs are available.
_IDLE_SLEEP_SECONDS = 30

# Reclaim loop interval.
_RECLAIM_INTERVAL_SECONDS = 300  # 5 minutes


class PathInsightWorker:
    """Claims and processes path insight jobs from the work queue.

    One instance per process.  To scale horizontally, launch multiple
    ``path-insight-worker`` containers — each gets a unique ``instance_uuid``
    so SKIP LOCKED ensures disjoint claim sets.

    Args:
    ----
        session_factory: Write session factory for intelligence_db.
        job_repo_factory: Callable that returns a PathInsightJobRepository for
                          a given session.
        insight_repo_factory: Callable that returns a PathInsightRepository for
                              a given session.
        path_discovery: PathDiscovery adapter (AGE session factory injected).
        scorer: PathScorer service.
        template_matcher: PathTemplateMatcher service.
        instance_uuid: Stable worker identity used for SKIP LOCKED claim.
        batch_size: Number of jobs to claim per cycle.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
        path_discovery: PathDiscovery,
        scorer: PathScorer,
        template_matcher: PathTemplateMatcher,
        instance_uuid: UUID,
        batch_size: int = 10,
    ) -> None:
        self._sf = session_factory
        self._path_discovery = path_discovery
        self._scorer = scorer
        self._template_matcher = template_matcher
        self._instance_uuid = instance_uuid
        self._batch_size = batch_size

    def _job_repo(self, session: AsyncSession) -> PathInsightJobRepository:
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        return PathInsightJobRepository(session)

    def _insight_repo(self, session: AsyncSession) -> PathInsightRepository:
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        return PathInsightRepository(session)

    async def run_loop(self) -> None:
        """Main claim-and-process loop.  Runs indefinitely until cancelled.

        Spawns a background reclaim task before entering the main loop so
        stuck jobs are automatically recovered (BP-112).
        """
        reclaim_task = asyncio.create_task(self._reclaim_loop(), name="path_insight_reclaim")
        try:
            while True:
                jobs = await self._claim_batch()
                if not jobs:
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                logger.info(  # type: ignore[no-any-return]
                    "path_insight_worker_claimed_batch",
                    count=len(jobs),
                    instance_uuid=str(self._instance_uuid),
                )
                await asyncio.gather(*[self._process_job(job) for job in jobs])
        finally:
            reclaim_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await reclaim_task

    async def _claim_batch(self) -> list[PathInsightJob]:
        """Claim a batch of pending jobs from the DB."""
        async with self._sf() as session:
            repo = self._job_repo(session)
            jobs = await repo.claim_batch(self._instance_uuid, batch_size=self._batch_size)
            await session.commit()
        return jobs

    async def _process_job(self, job: PathInsightJob) -> None:
        """Process a single job: discover paths → score → persist → mark done.

        BP-113: ALL exceptions are caught and routed to mark_failed so the job
        never stays permanently stuck in 'running'.
        """
        try:
            # Phase 1: discover paths via AGE (no DB session held).
            raw_paths = await self._path_discovery.find_paths_for_anchor(job.entity_id)

            # Phase 2: score and apply template matching (CPU, no I/O).
            all_insights = []
            for raw in raw_paths:
                template = await self._template_matcher.match(raw)
                insight = self._scorer.score(raw, raw_paths, template_match=template)
                all_insights.append(insight)

            # Phase 3: take top-50 by composite score.
            top_insights = sorted(all_insights, key=lambda i: i.composite_score, reverse=True)[:_TOP_K]

            # Phase 4: persist results + mark done (single transaction).
            async with self._sf() as session:
                insight_repo = self._insight_repo(session)
                await insight_repo.replace_for_anchor(job.entity_id, top_insights)
                job_repo = self._job_repo(session)
                await job_repo.mark_done(job.job_id, paths_found=len(top_insights))
                await session.commit()

            logger.info(  # type: ignore[no-any-return]
                "path_insight_job_done",
                job_id=str(job.job_id),
                entity_id=str(job.entity_id),
                paths_found=len(top_insights),
            )

        except Exception as exc:
            # BP-113: never leave job in 'running' state.
            logger.error(  # type: ignore[no-any-return]
                "path_insight_job_failed",
                job_id=str(job.job_id),
                entity_id=str(job.entity_id),
                error=str(exc),
            )
            try:
                async with self._sf() as session:
                    job_repo = self._job_repo(session)
                    await job_repo.mark_failed(job.job_id, error_text=str(exc)[:2000])
                    await session.commit()
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "path_insight_mark_failed_error",
                    job_id=str(job.job_id),
                    exc_info=True,
                )

    async def _reclaim_loop(self) -> None:
        """Periodically reclaim stuck jobs (BP-112 pattern).

        Runs every 5 minutes.  Resets jobs that have been in 'running' state
        for more than 10 minutes back to 'pending'.
        """
        while True:
            await asyncio.sleep(_RECLAIM_INTERVAL_SECONDS)
            try:
                async with self._sf() as session:
                    repo = self._job_repo(session)
                    count = await repo.reclaim_stuck(timeout_seconds=600)
                    await session.commit()
                if count:
                    logger.info(  # type: ignore[no-any-return]
                        "path_insight_reclaimed_stuck_jobs",
                        count=count,
                    )
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "path_insight_reclaim_error",
                    exc_info=True,
                )
