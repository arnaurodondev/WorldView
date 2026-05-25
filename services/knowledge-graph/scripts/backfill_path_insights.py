"""One-time backfill: explain stale ``path_insights`` rows in batches.

Context (FIX-LIVE-GG, INV-LIVE-GG cluster 3, 2026-05-25):
  The SLO test ``test_path_insight_llm_explanation_coverage`` flagged 4 710
  rows where ``llm_explanation IS NULL AND computed_at < now() - interval '1 hour'``.
  The streaming ``PathExplanationBatchWorker`` drains roughly 1 266 rows/hour
  after the FIX-LIVE-HH2 tuning, so the backlog would drain in ~3.7 h on its
  own — but the worker also competes with new path-insight rows being
  produced by ``PathInsightWorker`` continuously.  This script lets an
  operator force the backlog to zero in one explicit run without waiting for
  the slow streaming drain.

How to run::

    docker exec worldview-knowledge-graph-1 \\
        python -m scripts.backfill_path_insights

Options (env vars, all optional)::

    BACKFILL_BATCH_SIZE=200       # rows per SELECT/process batch
    BACKFILL_CONCURRENCY=5        # max parallel LLM calls within a batch
    BACKFILL_MAX_ROWS=0           # cap total rows processed (0 = no cap; drain everything)
    BACKFILL_DRY_RUN=false        # when true, print the SELECT plan + counts only

The script reuses the same ``PathExplanationService`` and ``FallbackChainClient``
wiring that the scheduler builds, so a stale row processed here is
indistinguishable from one processed by the streaming worker.

Exit codes::

    0   — successful drain (final stale-count == 0 OR cap reached cleanly)
    1   — fatal wiring error (missing API key, DB unreachable, etc.)
    2   — partial drain — some rows still NULL after the cap was hit
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.services.path_explanation_service import (
        PathExplanationService,
    )
    from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode


logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── env-var knobs ──────────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    """Parse a positive int env var; fall back to ``default`` on error."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("backfill_invalid_env_int", name=name, raw=raw, fallback=default)
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    """Parse a truthy/falsy env var (``true``/``yes``/``1`` → True)."""
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "yes", "1", "on"}


# ── core backfill loop ────────────────────────────────────────────────────


async def _count_stale(session_factory: Any) -> int:
    """Return the current number of stale path_insight rows.

    A stale row = NULL explanation AND ``computed_at`` older than 1 h (so
    fresh rows that the streaming worker is about to process don't count).
    """
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT count(*)
                FROM path_insights
                WHERE llm_explanation IS NULL
                  AND computed_at < now() - interval '1 hour'
            """)
        )
        row = result.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def _fetch_batch(
    session_factory: Any,
    batch_size: int,
) -> list[tuple[UUID, list[PathNode], list[PathEdge]]]:
    """SELECT one batch of stale rows ordered by composite_score DESC.

    Mirrors ``PathExplanationBatchWorker._fetch_unexplained_batch`` so the
    backfill and the streaming worker pick rows in the same order — highest
    value paths get explained first regardless of which path drains them.
    """
    import json

    from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT insight_id, path_nodes, path_edges
                FROM path_insights
                WHERE llm_explanation IS NULL
                  AND computed_at < now() - interval '1 hour'
                ORDER BY composite_score DESC
                LIMIT :lim
            """),
            {"lim": batch_size},
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
                )
                for item in edges_data
            ]
            parsed.append((insight_id, path_nodes, path_edges))
        except Exception:
            # One bad row should never abort the batch — log and skip.
            logger.warning(
                "backfill_row_parse_error",
                row_id=str(row[0]) if row else "unknown",
                exc_info=True,
            )
    return parsed


async def _process_batch(
    rows: list[tuple[UUID, list[PathNode], list[PathEdge]]],
    explanation_service: PathExplanationService,
    concurrency: int,
) -> dict[str, int]:
    """Process one batch of (insight_id, nodes, edges) tuples.

    Bounded concurrency via asyncio.Semaphore so we don't blow past
    DeepInfra's rate limit when several batches run back-to-back.  Failures
    are caught per-row (BP-112/BP-113 pattern) — one flaky LLM call must
    never skip the rest of the batch.
    """
    counters = {"generated": 0, "failed": 0}
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_one(insight_id: UUID, nodes: list[PathNode], edges: list[PathEdge]) -> None:
        async with semaphore:
            try:
                await explanation_service.generate_explanation(
                    insight_id=insight_id,
                    path_nodes=nodes,
                    path_edges=edges,
                )
                async with lock:
                    counters["generated"] += 1
            except Exception:
                logger.warning(
                    "backfill_item_failed",
                    insight_id=str(insight_id),
                    exc_info=True,
                )
                async with lock:
                    counters["failed"] += 1

    await asyncio.gather(*[_process_one(*row) for row in rows])
    return counters


async def main() -> int:
    """Wire everything up and run the backfill loop."""
    # Local imports so module load never fails when invoked for --help in a
    # half-configured env (e.g. without DB env vars).
    from knowledge_graph.application.services.path_explanation_service import (
        PathExplanationService,
    )
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
        PathInsightRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-backfill",
        level=settings.log_level,
        json=settings.log_json,
    )

    batch_size = _env_int("BACKFILL_BATCH_SIZE", 200)
    concurrency = _env_int("BACKFILL_CONCURRENCY", 5)
    max_rows = _env_int("BACKFILL_MAX_ROWS", 0)  # 0 = drain everything
    dry_run = _env_bool("BACKFILL_DRY_RUN", False)

    logger.info(
        "backfill_starting",
        batch_size=batch_size,
        concurrency=concurrency,
        max_rows_cap=max_rows or "unlimited",
        dry_run=dry_run,
    )

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    stale_before = await _count_stale(write_factory)
    logger.info("backfill_initial_count", stale_rows=stale_before)

    if dry_run:
        logger.info("backfill_dry_run_complete", stale_rows=stale_before)
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()
        return 0

    if stale_before == 0:
        logger.info("backfill_nothing_to_do")
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()
        return 0

    # ── Wire the DeepInfra extraction client + service (mirror scheduler_main) ──
    api_key = settings.deepinfra_api_key.get_secret_value()  # DEF-005
    if not api_key:
        logger.error(
            "backfill_aborting_no_deepinfra_key",
            reason=(
                "KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY is empty — "
                "PathExplanationService would silently no-op. "
                "Set the key in docker.env and retry."
            ),
        )
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()
        return 1

    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter  # type: ignore[import-untyped]

    deepinfra_ext = DeepSeekExtractionAdapter(
        api_key=api_key,
        model_id=settings.deepinfra_extraction_model_id,
        base_url=settings.deepinfra_extraction_base_url,
        semaphore=asyncio.Semaphore(settings.deepinfra_extraction_concurrency),
    )
    llm_client = FallbackChainClient(
        deepinfra_extraction=deepinfra_ext,
        ollama_embedding=None,
        ollama_extraction=None,
        retry_delays_deepinfra=(5.0, 15.0),
        retry_delays_ollama=(),
    )

    # ── Wrap the repo so each update_explanation opens its own write session ──
    # Mirrors ``_build_explanation_service`` in the scheduler — see comments
    # there.  We can't re-use the scheduler's helper directly because it's a
    # closure inside the scheduler module, but the contract is small enough
    # to inline.
    class _SessionBoundRepoAdapter:
        def __init__(self, sf: Any, repo_cls: Any) -> None:
            self._sf = sf
            self._repo_cls = repo_cls

        async def update_explanation(
            self,
            insight_id: UUID,
            explanation_text: str,
            model_id: str,
        ) -> None:
            async with self._sf() as session:
                repo = self._repo_cls(session)
                await repo.update_explanation(insight_id, explanation_text, model_id)
                await session.commit()

    explanation_service = PathExplanationService(
        path_insight_repo=_SessionBoundRepoAdapter(write_factory, PathInsightRepository),  # type: ignore[arg-type]
        llm_client=llm_client,
        model_id=getattr(settings, "narrative_llm_model_id", "meta-llama/Meta-Llama-3.1-8B-Instruct"),
    )

    # ── Drain loop ────────────────────────────────────────────────────────
    totals = {"generated": 0, "failed": 0, "batches": 0}
    processed = 0
    try:
        while True:
            # Respect the optional max_rows cap.
            if max_rows and processed >= max_rows:
                logger.info("backfill_cap_reached", max_rows=max_rows, processed=processed)
                break

            # Right-size the next batch so we don't overshoot the cap by
            # batch_size-1 rows on the last iteration.
            this_batch = batch_size
            if max_rows:
                this_batch = min(batch_size, max_rows - processed)

            rows = await _fetch_batch(write_factory, this_batch)
            if not rows:
                logger.info("backfill_drained")
                break

            counters = await _process_batch(rows, explanation_service, concurrency)
            totals["generated"] += counters["generated"]
            totals["failed"] += counters["failed"]
            totals["batches"] += 1
            processed += len(rows)
            logger.info(
                "backfill_batch_complete",
                batch_no=totals["batches"],
                rows_in_batch=len(rows),
                generated=counters["generated"],
                failed=counters["failed"],
                processed_total=processed,
            )
    finally:
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await _read_engine.dispose()

    stale_after = await _count_stale_safely(settings)
    logger.info(
        "backfill_complete",
        batches=totals["batches"],
        generated=totals["generated"],
        failed=totals["failed"],
        stale_before=stale_before,
        stale_after=stale_after,
    )

    # Exit 0 if we drained everything OR we hit a clean cap.  Exit 2 if rows
    # still remain after we exited the loop without a cap (would indicate
    # systematic LLM failures).
    if max_rows and processed >= max_rows:
        return 0
    return 0 if stale_after == 0 else 2


async def _count_stale_safely(settings: Any) -> int:
    """Open a fresh factory pair purely to read the post-run stale count.

    Done in a separate connection because the main factories are already
    disposed by the time we reach the final summary log.  Failures here are
    swallowed — the exit code from ``main`` is the source of truth.
    """
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

    try:
        engine, read_engine, write_factory, _read_factory = _build_factories(settings)
        count = await _count_stale(write_factory)
        await engine.dispose()
        with contextlib.suppress(Exception):
            await read_engine.dispose()
        return count
    except Exception:
        logger.warning("backfill_final_count_failed", exc_info=True)
        return -1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
