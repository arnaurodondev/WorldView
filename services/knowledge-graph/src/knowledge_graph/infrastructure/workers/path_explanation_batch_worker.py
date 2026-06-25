"""PathExplanationBatchWorker — sweep existing path_insights rows without LLM explanations.

Runs as a periodic APScheduler job (registered by KnowledgeGraphScheduler).

Implements the 3-phase pattern:
  Phase 1 (Read)  — SELECT up to ``batch_size`` insight_id rows whose
                    ``llm_explanation IS NULL``, ordered by composite_score DESC
                    so the highest-value paths are explained first.
  Phase 2 (LLM)  — For each insight, call PathExplanationService.generate_explanation()
                    with bounded concurrency (semaphore).  No DB session is held
                    during LLM calls.
  Phase 3 (Write) — PathExplanationService persists each result via
                    update_explanation() in its own session.

BP-112/BP-113: failures are caught per-insight (never per-batch) so one flaky
LLM call does not skip the rest of the batch.

Task 3 (2026-05-23): this worker also serves as the consumer for existing
12,689 path_insights rows that were created before Wave E2 (they all have
llm_explanation=NULL).  On each scheduler tick it drains a batch of
``batch_size`` rows until the table is fully explained.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.services.path_explanation_service import PathExplanationService
    from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum concurrent LLM calls per sweep to avoid overwhelming the provider.
_DEFAULT_CONCURRENCY = 5

# Maximum rows fetched per sweep.  Each row triggers one LLM call (~200 tokens).
# At concurrency=5 and ~500ms/call this processes 200 rows in ~20s per tick.
_DEFAULT_BATCH_SIZE = 200


class PathExplanationBatchWorker:
    """Sweep path_insights rows without llm_explanation and generate them in bulk.

    Args:
    ----
        session_factory:     Write session factory for intelligence_db.
        explanation_service: PathExplanationService instance (must have non-None
                             llm_client, otherwise all calls are no-ops).
        batch_size:          Number of insight rows to process per scheduler tick.
        concurrency:         Max parallel LLM calls within a single tick.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
        explanation_service: PathExplanationService,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self._sf = session_factory
        self._explanation_service = explanation_service
        self._batch_size = batch_size
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self) -> None:
        """APScheduler-compatible entry point.

        Phase 0 (PLAN-0093 D-1, T-D-1-02): refresh the
                ``path_insight_explanation_pending_total`` gauge so Prometheus
                always exposes the current backlog even on idle ticks.
        Phase 0b (PLAN-0093 D-1, T-D-1-03): null-guard — if the explanation
                service has no LLM client wired, log CRITICAL and short-circuit
                the cycle instead of silently looping forever while writing
                NULL explanations.  HR-031 silent-failure prevention.
        Phase 1: fetch a batch of un-explained insights (READ, no LLM).
        Phase 2: call PathExplanationService for each (LLM, no session).
        Phase 3: PathExplanationService persists each result in its own session.
        """
        # Phase 0 — update the pending-explanation gauge.  Best-effort: a
        # transient SELECT failure must not crash the worker; the LLM phase is
        # what actually matters.
        await self._update_pending_gauge()

        # Phase 0b — fail-fast guard (HR-031): the only way the explanation
        # service is a no-op is when the LLM client is None (DEEPINFRA_API_KEY
        # missing or every provider in the fallback chain unconfigured).  In
        # that state we must NOT keep looping silently — emit a CRITICAL log
        # and return without touching the DB.  The next scheduler tick will
        # re-check (so transient credential rotation is handled).
        if getattr(self._explanation_service, "_llm", None) is None:
            logger.critical(  # type: ignore[no-any-return]
                "path_insight_llm_client_unavailable",
                reason="explanation_service.llm is None — check DEEPINFRA_API_KEY / fallback chain",
            )
            return

        rows = await self._fetch_unexplained_batch()
        if not rows:
            logger.info("path_explanation_batch_worker_no_rows")  # type: ignore[no-any-return]
            return

        logger.info(  # type: ignore[no-any-return]
            "path_explanation_batch_worker_start",
            batch_size=len(rows),
        )

        counters = {"generated": 0, "skipped": 0, "failed": 0}
        lock = asyncio.Lock()

        async def _process_one(
            insight_id: UUID,
            path_nodes: list[PathNode],
            path_edges: list[PathEdge],
        ) -> None:
            async with self._semaphore:
                try:
                    await self._explanation_service.generate_explanation(
                        insight_id=insight_id,
                        path_nodes=path_nodes,
                        path_edges=path_edges,
                    )
                    async with lock:
                        counters["generated"] += 1
                except Exception:
                    logger.warning(  # type: ignore[no-any-return]
                        "path_explanation_batch_item_failed",
                        insight_id=str(insight_id),
                        exc_info=True,
                    )
                    async with lock:
                        counters["failed"] += 1

        await asyncio.gather(*[_process_one(*row) for row in rows])

        logger.info(  # type: ignore[no-any-return]
            "path_explanation_batch_worker_complete",
            **counters,
        )

    async def _update_pending_gauge(self) -> None:
        """Refresh ``path_insight_explanation_pending_total`` (T-D-1-02).

        Counts ``path_insights`` rows where ``llm_explanation IS NULL`` AND
        ``computed_at`` is older than 1 hour — so freshly-seeded rows that
        are about to be explained on this very tick are not counted as a
        backlog.

        Best-effort: any DB failure here is swallowed (warning log).  The
        worker's job is to generate explanations, not to compute metrics —
        a transient SELECT failure must not block the LLM phase.
        """
        from knowledge_graph.infrastructure.metrics.prometheus import (
            path_insight_explanation_pending_total,
        )

        try:
            async with self._sf() as session:
                result = await session.execute(
                    text("""
SELECT count(*)
FROM path_insights
WHERE llm_explanation IS NULL
  AND computed_at < now() - interval '1 hour'
""")
                )
                row = result.fetchone()
                pending = int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "path_insight_pending_gauge_update_failed",
                error=str(exc),
            )
            return

        path_insight_explanation_pending_total.set(pending)

    async def _fetch_unexplained_batch(
        self,
    ) -> list[tuple[UUID, list[PathNode], list[PathEdge]]]:
        """Phase 1: SELECT up to batch_size insight rows with llm_explanation IS NULL.

        Returns a list of (insight_id, path_nodes, path_edges) tuples so the
        caller can call generate_explanation() without holding the DB session.
        """
        import json

        from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode

        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT insight_id, path_nodes, path_edges
FROM path_insights
WHERE llm_explanation IS NULL
ORDER BY composite_score DESC
LIMIT :lim
"""),
                {"lim": self._batch_size},
            )
            rows = result.fetchall()

        parsed: list[tuple[UUID, list[PathNode], list[PathEdge]]] = []
        for row in rows:
            try:
                insight_id = UUID(str(row[0]))
                nodes_data = row[1] if isinstance(row[1], list) else json.loads(str(row[1]))
                edges_data = row[2] if isinstance(row[2], list) else json.loads(str(row[2]))

                path_nodes = [
                    PathNode(
                        entity_id=UUID(str(item["entity_id"])),
                        name=str(item["name"]),
                        entity_type=str(item["entity_type"]),
                    )
                    for item in nodes_data
                ]
                path_edges = [
                    PathEdge(
                        relation_type=str(item["relation_type"]),
                        confidence=float(item["confidence"]),
                        # Pre-fix rows lack ``forward`` → default True (R11
                        # forward-compat read); the explanation prompt then renders
                        # true subject→object via PathExplanationService._build_prompt.
                        forward=bool(item.get("forward", True)),
                    )
                    for item in edges_data
                ]
                parsed.append((insight_id, path_nodes, path_edges))
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "path_explanation_batch_row_parse_error",
                    row_id=str(row[0]) if row else "unknown",
                    exc_info=True,
                )
        return parsed
