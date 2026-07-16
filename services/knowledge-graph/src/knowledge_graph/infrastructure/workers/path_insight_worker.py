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
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.node_degree_repository import GraphStats
from knowledge_graph.application.services.weirdness_scorer import WeirdnessScorer
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_DEFINITION,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine, RawPath
    from knowledge_graph.application.ports.node_degree_repository import (
        NodeDegreeRepositoryPort,
    )
    from knowledge_graph.application.services.path_scorer import PathScorer
    from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher
    from knowledge_graph.config import Settings
    from knowledge_graph.domain.entities.path_insight import PathInsight, PathInsightJob
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
        PathInsightJobRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
        PathInsightRepository,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum insights stored per anchor entity (PRD-0074 §9.3).
_TOP_K = 50

# Default per-anchor discovery hop ceiling (PLAN-0112 W2) — mirrors
# ``Settings.path_max_hops``.  Injected via the constructor; this constant is the
# fallback when the caller does not pass an explicit value.
_DEFAULT_PATH_MAX_HOPS = 3

# Max raw paths pulled from the engine per anchor before scoring/top-K trim.
# The engine accumulates across hop depths up to this cap (its own _MAX_LIMIT is
# 200); we request a generous-but-bounded set so the top-50 selection has headroom.
_DISCOVERY_LIMIT = 200

# Sleep when no jobs are available.
_IDLE_SLEEP_SECONDS = 30

# Reclaim loop interval.
_RECLAIM_INTERVAL_SECONDS = 300  # 5 minutes


def _safe_uuid(value: object) -> UUID | None:
    """Parse a UUID string, returning None on malformed input (no raise)."""
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _parse_pgvector(text_value: object) -> list[float]:
    """Parse a pgvector ``::text`` value (e.g. ``"[0.1,0.2,...]"``) to a float list."""
    if text_value is None:
        return []
    s = str(text_value).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s:
        return []
    try:
        return [float(x) for x in s.split(",")]
    except ValueError:
        return []


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
        path_engine: GraphPathEngine port (AGE-backed adapter injected) — replaces
                     the deprecated PathDiscovery (PLAN-0112 T-2-04).  The worker
                     depends on the ABC, not the concrete adapter (R25).
        scorer: PathScorer service.
        template_matcher: PathTemplateMatcher service.
        instance_uuid: Stable worker identity used for SKIP LOCKED claim.
        batch_size: Number of jobs to claim — and process CONCURRENTLY via
                    ``asyncio.gather`` — per cycle.  PLAN-0111 A-5: lowered from
                    10 to 3.  Each job fires a 2-hop AND a 3-hop AGE query, so a
                    batch of 10 launched up to 20 heavy edge-expansion queries
                    against Postgres at once, saturating it so they ALL breached
                    the per-query statement_timeout and failed together.  Three
                    concurrent jobs (≤6 in-flight queries) keeps Postgres below
                    that cliff while still parallelising the work.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
        path_engine: GraphPathEngine,
        scorer: PathScorer,
        template_matcher: PathTemplateMatcher,
        instance_uuid: UUID,
        batch_size: int = 3,
        path_max_hops: int = _DEFAULT_PATH_MAX_HOPS,
        node_degree_repo_factory: Callable[[AsyncSession], NodeDegreeRepositoryPort] | None = None,
        settings: Settings | None = None,
        prune_membership: bool = True,
        path_min_hops: int = 2,
    ) -> None:
        self._sf = session_factory
        self._path_engine = path_engine
        # Data-coverage fix 2026-07-16: membership pruning + hop window are now
        # caller-supplied (from Settings via main).  The ctor DEFAULTS preserve
        # the historical behaviour (hard prune, min 2 hops) so existing tests and
        # any legacy wiring are unchanged; production main passes the relaxed
        # ``settings.path_prune_membership`` (False) so the star-graph feed is no
        # longer emptied by the post-hoc membership drop.
        self._prune_membership = prune_membership
        self._path_min_hops = path_min_hops
        # PathScorer kept for back-compat (W6 removal) but no longer used for
        # scoring: PLAN-0112 W3 swaps in WeirdnessScorer (T-3-04).
        self._scorer = scorer
        self._template_matcher = template_matcher
        self._instance_uuid = instance_uuid
        self._batch_size = batch_size
        self._path_max_hops = path_max_hops
        # PLAN-0112 W3 (T-3-04): the degree repo + settings power WeirdnessScorer.
        # When None (legacy/tests) the worker falls back to the deprecated
        # PathScorer so existing wiring keeps working until main is updated.
        self._node_degree_repo_factory = node_degree_repo_factory
        self._settings = settings

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
            # Phase 1: discover paths via the typed-VLE engine (membership-pruned,
            # PLAN-0112 T-2-04).  The source end is bound to the anchor, target end
            # free; the engine probes hop depths 1..path_max_hops (staged, BP-687)
            # and never expands the untyped frontier (BP-689).
            raw_paths = await self._path_engine.find_paths_from_anchor(
                job.entity_id,
                max_hops=self._path_max_hops,
                prune_membership=self._prune_membership,
                min_hops=self._path_min_hops,
                limit=_DISCOVERY_LIMIT,
            )

            # Self-loop guard (PLAN-0112 T-2-04): drop any path whose endpoints are
            # the same entity.  The engine already filters these, but the worker
            # guards too so a future engine change can't reintroduce self-loops
            # into the scored output (the scorer zeroes them in W3 regardless).
            raw_paths = [p for p in raw_paths if p.node_ids and p.node_ids[0] != p.node_ids[-1]]

            # Phase 2: score via the WeirdnessScorer (PLAN-0112 W3, T-3-04).
            # When the degree repo + settings are wired we pre-fetch all global
            # lookups once and score each path purely; otherwise we fall back to
            # the deprecated PathScorer (legacy wiring / tests).
            if self._node_degree_repo_factory is not None and self._settings is not None:
                all_insights = await self._score_with_weirdness(raw_paths)
            else:
                all_insights = []
                for raw in raw_paths:
                    template = await self._template_matcher.match(raw)
                    all_insights.append(self._scorer.score(raw, raw_paths, template_match=template))

            # Phase 3: take top-50 by composite score (== weirdness post-W3).
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
                    new_status = await job_repo.mark_failed(job.job_id, error_text=str(exc)[:2000])
                    await session.commit()
                # PLAN-0112 T-1-03 (§13): count only the terminal transition so
                # ``path_jobs_failed_total`` rate > 0 sustained = the flood is back.
                if new_status == "failed":
                    from knowledge_graph.infrastructure.metrics.prometheus import (
                        path_jobs_failed_total,
                    )

                    path_jobs_failed_total.inc()
            except Exception:
                logger.error(  # type: ignore[no-any-return]
                    "path_insight_mark_failed_error",
                    job_id=str(job.job_id),
                    exc_info=True,
                )

    async def _score_with_weirdness(self, raw_paths: list[RawPath]) -> list[PathInsight]:
        """Pre-fetch global lookups then score every path with WeirdnessScorer.

        The scorer is PURE (no DB); we therefore gather all data it needs in a
        handful of batch queries first, then build dict-backed closures:
          • degree / meaningful-degree → the whole node_degree map (one query).
          • graph_stats → the single normaliser row.
          • definition embeddings → only the endpoint entity_ids on these paths.
          • first_evidence_at → only the rel_ids on these paths.
        Fail-open: missing degree → 1 (max surprise), missing embedding → type
        fallback, missing first_seen → not-recent (BP-540/541 degrade, not crash).
        """
        assert self._node_degree_repo_factory is not None  # guarded by caller
        assert self._settings is not None

        # Collect the entity_ids (endpoints + all nodes) and rel_ids referenced.
        endpoint_ids: set[UUID] = set()
        rel_ids: set[UUID] = set()
        for p in raw_paths:
            for nid in p.node_ids:
                parsed = _safe_uuid(nid)
                if parsed is not None:
                    endpoint_ids.add(parsed)
            rel_ids.update(p.rel_ids)

        async with self._sf() as session:
            await session.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
            degree_repo = self._node_degree_repo_factory(session)
            degree_map = await degree_repo.get_degree_map()
            stats = await degree_repo.get_graph_stats() or GraphStats(0, 0, 0)
            embeddings = await self._fetch_definition_embeddings(session, endpoint_ids)
            first_seen = await self._fetch_first_seen(session, rel_ids)
            # BUG-2 guard: a path endpoint can be a non-canonical AGE vertex
            # (sync-gap / seed node), and dst_entity_id has an FK to
            # canonical_entities.  Prefetch which of the referenced ids ARE
            # canonical so we can NULL dst_entity_id for the rest (FK-safe).
            canonical_ids = await self._fetch_canonical_ids(session, endpoint_ids)

        st = self._settings
        scorer = WeirdnessScorer(
            degree_of=lambda eid: degree_map.get(eid, (1, 1))[0],
            meaningful_degree_of=lambda eid: degree_map.get(eid, (1, 1))[1],
            graph_stats=stats,
            embedding_of=lambda eid: embeddings.get(eid),
            first_seen_of=lambda rid: first_seen.get(rid),
            novelty_window=timedelta(days=st.novelty_window_days),
            w_unexpectedness=st.weirdness_w_unexpectedness,
            w_semantic=st.weirdness_w_semantic,
            w_novelty=st.weirdness_w_novelty,
            unexpectedness_mode=st.weirdness_unexpectedness_mode,
        )
        scored = [scorer.score(raw) for raw in raw_paths]

        # BUG-2: NULL dst_entity_id for any endpoint that is not a known canonical
        # entity, so the FK on path_insights.dst_entity_id can never be violated
        # (we keep the FK for referential integrity on REAL endpoints).
        return [
            replace(ins, dst_entity_id=None)
            if ins.dst_entity_id is not None and ins.dst_entity_id not in canonical_ids
            else ins
            for ins in scored
        ]

    @staticmethod
    async def _fetch_canonical_ids(
        session: AsyncSession,
        entity_ids: set[UUID],
    ) -> set[UUID]:
        """Return the subset of ``entity_ids`` that exist in ``canonical_entities``."""
        if not entity_ids:
            return set()
        result = await session.execute(
            text("SELECT entity_id FROM canonical_entities WHERE entity_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(e) for e in entity_ids]},
        )
        return {UUID(str(row[0])) for row in result.fetchall()}

    @staticmethod
    async def _fetch_definition_embeddings(
        session: AsyncSession,
        entity_ids: set[UUID],
    ) -> dict[UUID, list[float]]:
        """Batch-fetch definition-view embeddings for the given entity_ids."""
        if not entity_ids:
            return {}
        result = await session.execute(
            text(
                "SELECT entity_id, embedding::text FROM entity_embedding_state "
                "WHERE view_type = :vt AND embedding IS NOT NULL "
                "AND entity_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"vt": VIEW_DEFINITION, "ids": [str(e) for e in entity_ids]},
        )
        out: dict[UUID, list[float]] = {}
        for row in result.fetchall():
            vec = _parse_pgvector(row[1])
            if vec:
                out[UUID(str(row[0]))] = vec
        return out

    @staticmethod
    async def _fetch_first_seen(
        session: AsyncSession,
        rel_ids: set[UUID],
    ) -> dict[UUID, datetime]:
        """Batch-fetch each edge's first-seen timestamp for the novelty term.

        AGE↔relations sync gap (PRD FR-13): an AGE edge's ``relation_id`` often is
        NOT present in ``relations`` (live measurement: only ~46% of non-membership
        edges join ``relations`` directly) — so keying novelty solely on
        ``relations.first_evidence_at`` left novelty 0 for EVERY path.  The edge's
        ``relation_id`` IS, however, almost always present in ``relation_evidence``,
        so we COALESCE the authoritative ``relations.first_evidence_at`` with
        ``MIN(relation_evidence.evidence_date)`` as the fallback.  Live coverage of
        non-membership edges rises from 2,413 → 4,530 / 5,260 with this fallback,
        and recent-edge count from 2,413 → 2,741 — making novelty meaningfully
        non-zero.  Best-effort: an edge absent from BOTH sources is simply treated
        as not-recent (novelty contribution 0), never an error (BP-540/541).
        """
        if not rel_ids:
            return {}
        ids = [str(r) for r in rel_ids]
        result = await session.execute(
            text(
                # LEFT JOIN ``relations`` (authoritative); fall back to the
                # earliest ``relation_evidence.evidence_date`` for sync-gap edges.
                "SELECT ids.rid, "
                "       COALESCE(r.first_evidence_at, ev.min_evidence_date) AS first_seen "
                "FROM unnest(CAST(:ids AS uuid[])) AS ids(rid) "
                "LEFT JOIN relations r ON r.relation_id = ids.rid "
                "LEFT JOIN ( "
                "    SELECT relation_id, MIN(evidence_date) AS min_evidence_date "
                "    FROM relation_evidence "
                "    WHERE relation_id = ANY(CAST(:ids AS uuid[])) "
                "    GROUP BY relation_id "
                ") ev ON ev.relation_id = ids.rid"
            ),
            {"ids": ids},
        )
        return {UUID(str(row[0])): row[1] for row in result.fetchall() if row[1] is not None}

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
